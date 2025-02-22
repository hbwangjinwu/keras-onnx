###############################################################################
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for
# license information.
###############################################################################
import numpy
from .activation import activation_map
from ..proto import keras
from ..proto import onnx_proto
from ..common.onnx_ops import apply_identity, apply_softmax, apply_transpose


activation_get = keras.activations.get
SeparableConv2D = keras.layers.SeparableConv2D
DepthwiseConv2D = keras.layers.DepthwiseConv2D if \
    hasattr(keras.layers, 'DepthwiseConv2D') else None
SeparableConv1D = keras.layers.SeparableConv1D if \
    hasattr(keras.layers, 'SeparableConv1D') else None


def _calc_explicit_padding(input_size, output_shape, output_padding, kernel_shape, stride, dilation, perm):
    to_nchw = lambda x, perm: [x[perm[n_]] for n_ in range(len(x))]
    input_size = to_nchw(input_size, perm)[2:]
    output_shape = to_nchw(output_shape, perm)[2:]

    spatial = len(kernel_shape)
    total_padding = []
    pads = [None] * 2 * spatial
    for i in range(spatial):
        total_padding[i:] = [stride[i] * (output_shape[i] - 1) +
                             output_padding[i] + kernel_shape[i] * dilation[i] - input_size[i]]
        pads[i] = total_padding[i] // 2
        pads[i + spatial] = total_padding[i] - (total_padding[i] // 2)

    return pads


def process_separable_conv_2nd(scope, operator, container, convolution_input_names, n_dims,
                               weight_perm_axes, parameters, auto_pad):
    attrs = {'name': operator.full_name + '1'}

    weight_tensor_name = scope.get_unique_variable_name('W')
    weight_params = parameters[1].transpose(weight_perm_axes)
    container.add_initializer(weight_tensor_name, onnx_proto.TensorProto.FLOAT,
                              weight_params.shape, weight_params.flatten())
    convolution_input_names.append(weight_tensor_name)

    if len(parameters) == 3:
        bias_tensor_name = scope.get_unique_variable_name('B')
        container.add_initializer(bias_tensor_name, onnx_proto.TensorProto.FLOAT,
                                  parameters[2].shape, parameters[2].flatten())
        convolution_input_names.append(bias_tensor_name)

    all_ones = numpy.ones(n_dims, numpy.int8)
    attrs['dilations'] = all_ones
    attrs['strides'] = all_ones
    attrs['kernel_shape'] = all_ones
    attrs['group'] = 1
    attrs['auto_pad'] = auto_pad

    intermediate_output_name = scope.get_unique_variable_name('convolution_output')
    container.add_node('Conv', convolution_input_names,
                       intermediate_output_name, **attrs)
    return intermediate_output_name


def convert_keras_conv_core(scope, operator, container, is_transpose, n_dims, input_perm_axes,
                            output_perm_axes, weight_perm_axes):
    op = operator.raw_operator

    is_separable_conv = isinstance(op, SeparableConv2D) or isinstance(op, SeparableConv1D)

    channels_first = n_dims > 1 and op.data_format == 'channels_first'

    # Unless channels_first is the Keras data format, the inputs and weights in Keras v.s. ONNX
    # are reversed. This is annoying, and inefficient as we'll have to use transposes.
    if channels_first:
        adjusted_input_name = operator.inputs[0].full_name
    else:
        adjusted_input_name = scope.get_unique_variable_name('adjusted_input')
        apply_transpose(scope, operator.inputs[0].full_name, adjusted_input_name, container, perm=input_perm_axes)

    op_type = 'ConvTranspose' if is_transpose else 'Conv'
    convolution_input_names = [adjusted_input_name]
    parameters = op.get_weights()

    if is_separable_conv:
        attrs = {'name': operator.full_name + '0'}
        assert (len(parameters) == 3 if op.use_bias else 2)
    else:
        attrs = {'name': operator.full_name}
        assert (len(parameters) == 2 if op.use_bias else 1)

    weight_params = parameters[0]

    input_channels, output_channels = weight_params.shape[-2:]
    kernel_size = weight_params.shape[:-2]
    assert (kernel_size == op.kernel_size)

    if isinstance(op, DepthwiseConv2D):
        # see https://github.com/onnx/onnx-tensorflow/pull/266/files
        dm = op.depth_multiplier
        output_channels *= dm
        group = input_channels
        shape = weight_params.shape
        # weight_params = weight_params.transpose(weight_perm_axes)
        new_shape = shape[:2] + (1, shape[2] * shape[3])
        weight_params = numpy.reshape(weight_params, new_shape)
        weight_params = weight_params.transpose(weight_perm_axes)
    elif is_separable_conv:
        group = weight_params.shape[-2]
        shape = weight_params.shape
        new_shape = shape[:-2] + (1, shape[-2] * shape[-1])
        weight_params = numpy.reshape(weight_params, new_shape).transpose(weight_perm_axes)
    else:
        weight_params = weight_params.transpose(weight_perm_axes)
        group = 1

    weight_tensor_name = scope.get_unique_variable_name('W')
    container.add_initializer(weight_tensor_name, onnx_proto.TensorProto.FLOAT,
                              weight_params.shape, weight_params.flatten())
    convolution_input_names.append(weight_tensor_name)

    if len(parameters) == 2 and not is_separable_conv:
        bias_tensor_name = scope.get_unique_variable_name('B')
        container.add_initializer(bias_tensor_name, onnx_proto.TensorProto.FLOAT,
                                  parameters[1].shape, parameters[1].flatten())
        convolution_input_names.append(bias_tensor_name)

    attrs['dilations'] = list(op.dilation_rate)
    attrs['strides'] = list(op.strides)
    attrs['kernel_shape'] = op.kernel_size
    attrs['group'] = group

    input_shape = op._input_shape if hasattr(op, '_input_shape') else op.input_shape
    output_shape = op._output_shape if hasattr(op, '_output_shape') else op.output_shape

    if op.padding == 'valid':
        attrs['auto_pad'] = 'VALID'
    elif op.padding == 'same':
        if input_shape.count(None) > 1:
            if is_transpose:
                attrs['auto_pad'] = 'SAME_LOWER'  # the controversial def in onnx spec.
            else:
                attrs['auto_pad'] = 'SAME_UPPER'
        else:
            attrs['auto_pad'] = 'NOTSET'
            output_padding = [0] * len(op.kernel_size)
            if hasattr(op, 'output_padding') and op.output_padding is not None:
                output_padding = op.output_padding
            attrs['pads'] = _calc_explicit_padding(output_shape if is_transpose else input_shape,
                                                   input_shape if is_transpose else output_shape,
                                                   output_padding,
                                                   op.kernel_size,
                                                   op.strides,
                                                   op.dilation_rate,
                                                   list(range(
                                                       len(input_shape))) if channels_first else input_perm_axes)
    else:
        raise RuntimeError("Unsupported padding type '{}'".format(op.padding))

    intermediate_output_name = scope.get_unique_variable_name('convolution_output')
    container.add_node(op_type, convolution_input_names,
                       intermediate_output_name, **attrs)

    if is_separable_conv:
        intermediate_output_name = process_separable_conv_2nd(scope, operator, container, [intermediate_output_name],
                                                              n_dims,
                                                              weight_perm_axes, parameters, attrs['auto_pad'])

    # Permute the output back of its original format
    transpose_output_name = scope.get_unique_variable_name('transpose_output')
    if not channels_first:
        # Generate a final transposer.
        apply_transpose(scope, intermediate_output_name, transpose_output_name, container, perm=output_perm_axes)
    else:
        apply_identity(scope, intermediate_output_name, transpose_output_name, container)

    # The construction of convolution is done. Now, we create an activation operator to apply the activation specified
    # in this Keras layer.
    apply_activation_function = activation_map[op.activation]
    if op.activation in [activation_get('softmax'), keras.activations.softmax]:
        apply_softmax(scope, transpose_output_name, operator.outputs[0].full_name, container, axis=-1)
    else:
        apply_activation_function(scope, transpose_output_name, operator.outputs[0].full_name, container)




def get_converter_config(dims, is_conv_transpose):
    assert (dims in [1, 2, 3])
    input_perm = [0, dims + 1] + list(range(1, dims + 1))
    output_perm = [0] + list(range(2, dims + 2)) + [1]
    weight_perm = [dims + 1, dims] + list(range(dims))
    return is_conv_transpose, dims, input_perm, output_perm, weight_perm


def convert_keras_conv1d(scope, operator, container):
    is_transpose, n_dims, input_perm, output_perm, weight_perm = get_converter_config(1, False)
    convert_keras_conv_core(scope, operator, container, is_transpose, n_dims, input_perm, output_perm, weight_perm)


def convert_keras_conv2d(scope, operator, container):
    is_transpose, n_dims, input_perm, output_perm, weight_perm = get_converter_config(2, False)
    convert_keras_conv_core(scope, operator, container, is_transpose, n_dims, input_perm, output_perm, weight_perm)


def convert_keras_depthwise_conv_2d(scope, operator, container):
    is_transpose, n_dims, input_perm, output_perm, weight_perm = get_converter_config(2, False)
    convert_keras_conv_core(scope, operator, container, is_transpose, n_dims, input_perm, output_perm, weight_perm)


def convert_keras_conv3d(scope, operator, container):
    is_transpose, n_dims, input_perm, output_perm, weight_perm = get_converter_config(3, False)
    convert_keras_conv_core(scope, operator, container, is_transpose, n_dims, input_perm, output_perm, weight_perm)


def convert_keras_conv_transpose_2d(scope, operator, container):
    is_transpose, n_dims, input_perm, output_perm, weight_perm = get_converter_config(2, True)
    convert_keras_conv_core(scope, operator, container, is_transpose, n_dims, input_perm, output_perm, weight_perm)


def convert_keras_conv_transpose_3d(scope, operator, container):
    is_transpose, n_dims, input_perm, output_perm, weight_perm = get_converter_config(3, True)
    convert_keras_conv_core(scope, operator, container, is_transpose, n_dims, input_perm, output_perm, weight_perm)


def convert_keras_separable_conv1d(scope, operator, container):
    is_transpose, n_dims, input_perm, output_perm, weight_perm = get_converter_config(1, False)
    convert_keras_conv_core(scope, operator, container, is_transpose, n_dims, input_perm, output_perm, weight_perm)


def convert_keras_separable_conv2d(scope, operator, container):
    is_transpose, n_dims, input_perm, output_perm, weight_perm = get_converter_config(2, False)
    convert_keras_conv_core(scope, operator, container, is_transpose, n_dims, input_perm, output_perm, weight_perm)
