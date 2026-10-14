"""Stand-in for a face-swap app's model loading: a one-node ONNX graph that must run on the GPU."""
import sys

import numpy as np
import onnxruntime as ort
from onnx import TensorProto, helper

graph = helper.make_graph([helper.make_node("Relu", ["x"], ["y"])], "g",
                          [helper.make_tensor_value_info("x", TensorProto.FLOAT, [1, 4])],
                          [helper.make_tensor_value_info("y", TensorProto.FLOAT, [1, 4])])
model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
model.ir_version = 8
sess = ort.InferenceSession(model.SerializeToString(), providers=["CUDAExecutionProvider", "CPUExecutionProvider"])
print("Applied providers:", sess.get_providers())
sess.run(None, {"x": np.ones((1, 4), np.float32)})
if "CUDAExecutionProvider" not in sess.get_providers():
    sys.exit("FATAL: CUDA provider not available, fell back to CPU")
print("OK")
