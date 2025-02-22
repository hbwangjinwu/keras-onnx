# keras2onnx

|          | Linux | Windows |
|----------|-------|---------|
| keras.io | [![Build Status](https://dev.azure.com/onnxmltools/ketone/_apis/build/status/linux-conda-ci?branchName=master)](https://dev.azure.com/onnxmltools/ketone/_build/latest?definitionId=9&branchName=master) | [![Build Status](https://dev.azure.com/onnxmltools/ketone/_apis/build/status/win32-conda-ci?branchName=master)](https://dev.azure.com/onnxmltools/ketone/_build/latest?definitionId=10&branchName=master) | 
| tf.keras | [![Build Status](https://dev.azure.com/onnxmltools/ketone/_apis/build/status/linux-tf-keras-ci?branchName=master)](https://dev.azure.com/onnxmltools/ketone/_build/latest?definitionId=19&branchName=master) | [![Build Status](https://dev.azure.com/onnxmltools/ketone/_apis/build/status/win32-tf-keras-CI?branchName=master)](https://dev.azure.com/onnxmltools/ketone/_build/latest?definitionId=20&branchName=master) | 


# Introduction
The keras2onnx model converter enables users to convert Keras models into the [ONNX](https://onnx.ai) model format.
Initially, the Keras converter was developed in the project [onnxmltools](https://github.com/onnx/onnxmltools). keras2onnx converter development was moved into an [independent repository](https://github.com/onnx/keras-onnx) to support more kinds of Keras models and reduce the complexity of mixing multiple converters.

All Keras layers have been supported for conversion using keras2onnx since **ONNX opset 7**. Please refer to the [Keras documentation](https://keras.io/layers/about-keras-layers/) for details on Keras layers. The keras2onnx converter also supports the lambda/custom layer by working with the [tf2onnx](https://github.com/onnx/tensorflow-onnx) converter which is embedded directly into the source tree to avoid version conflicts and installation complexity.

Windows Machine Learning (WinML) users can use [WinMLTools](https://docs.microsoft.com/en-us/windows/ai/windows-ml/convert-model-winmltools) to convert their Keras models to the ONNX format. If you want to use the keras2onnx converter, please refer to the [WinML Release Notes](https://docs.microsoft.com/en-us/windows/ai/windows-ml/release-notes) to identify the corresponding ONNX opset for your WinML version.

keras2onnx has been tested on **Python 3.5, 3.6, and 3.7** (CI build). It does not support **Python 2.x**. The tf.keras support in the keras2onnx converter has been tested with **Tensorflow 1.13.1**.

# Notes

# tf.keras v.s. keras.io
Both Keras model types are now supported in the keras2onnx converter. If the user's Keras package was installed from [Keras.io](https://keras.io/), the converter converts the model as it was created by the keras.io package. Otherwise, it will convert it through [tf.keras](https://www.tensorflow.org/guide/keras).<br>

If you want to override this behaviour, please specify the environment variable TF_KERAS=1 before invoking the converter python API.

# Usage
Before running the converter, please notice that tensorflow has to be installed in your python environment,
you can choose **tensorflow** package(CPU version) or **tensorflow-gpu**(GPU version)
## Validate pre-trained Keras application models
It will be useful to convert the models from Keras to ONNX from a python script.
You can use the following API:
```
import keras2onnx
keras2onnx.convert_keras(model, name=None, doc_string='', target_opset=None, channel_first_inputs=None):
    # type: (keras.Model, str, str, int, []) -> onnx.ModelProto
    """
    :param model: keras model
    :param name: the converted onnx model internal name
    :param doc_string:
    :param target_opset:
    :param channel_first_inputs: A list of channel first input.
    :return:
    """
```

Use the following script to convert keras application models to onnx, and then perform inference:
```
import numpy as np
from keras.preprocessing import image
from keras.applications.resnet50 import preprocess_input
import keras2onnx
import onnxruntime

# image preprocessing
img_path = 'elephant.jpg'   # make sure the image is in img_path
img_size = 224
img = image.load_img(img_path, target_size=(img_size, img_size))
x = image.img_to_array(img)
x = np.expand_dims(x, axis=0)
x = preprocess_input(x)

# load keras model
from keras.applications.resnet50 import ResNet50
model = ResNet50(include_top=True, weights='imagenet')

# convert to onnx model
onnx_model = keras2onnx.convert_keras(model, model.name)

# runtime prediction
content = onnx_model.SerializeToString()
sess = onnxruntime.InferenceSession(content)
x = x if isinstance(x, list) else [x]
feed = dict([(input.name, x[n]) for n, input in enumerate(sess.get_inputs())])
pred_onnx = sess.run(None, feed)
```

An alternative way to load onnx model to runtime session is to save the model first:
```
import onnx
temp_model_file = 'model.onnx'
onnx.save_model(onnx_model, temp_model_file)
sess = onnxruntime.InferenceSession(temp_model_file)
```

We converted successfully for all the keras application models such as:
Xception, VGG16, VGG19, ResNet50, InceptionV3, InceptionResNetV2, MobileNet, MobileNetV2, DenseNet121, DenseNet169, DenseNet201, NASNetMobile, and NASNetLarge.
Try the following models and convert them to onnx using the code above.

```
from keras.applications.xception import Xception
model = Xception(include_top=True, weights='imagenet')

from keras.applications.vgg16 import VGG16
model = VGG16(include_top=True, weights='imagenet')

from keras.applications.vgg19 import VGG19
model = VGG19(include_top=True, weights='imagenet')

from keras.applications.resnet50 import ResNet50
model = ResNet50(include_top=True, weights='imagenet')

from keras.applications.inception_v3 import InceptionV3
model = InceptionV3(include_top=True, weights='imagenet')

from keras.applications.inception_resnet_v2 import InceptionResNetV2
model = InceptionResNetV2(include_top=True, weights='imagenet')

from keras.applications import mobilenet
model = mobilenet.MobileNet(weights='imagenet')

from keras.applications import mobilenet_v2
model = mobilenet_v2.MobileNetV2(weights='imagenet')

from keras.applications.densenet import DenseNet121
model = DenseNet121(include_top=True, weights='imagenet')

from keras.applications.densenet import DenseNet169
model = DenseNet169(include_top=True, weights='imagenet')

from keras.applications.densenet import DenseNet201
model = DenseNet201(include_top=True, weights='imagenet')

from keras.applications.nasnet import NASNetMobile
model = NASNetMobile(include_top=True, weights='imagenet')

from keras.applications.nasnet import NASNetLarge
model = NASNetLarge(include_top=True, weights='imagenet')
```

## Contribute
We welcome contributions in the form of feedback, ideas, or code.

## License
[MIT License](LICENSE)
