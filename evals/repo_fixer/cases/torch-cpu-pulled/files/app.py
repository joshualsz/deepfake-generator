"""Stand-in for the repo's entry point: loads a timm model on the GPU."""
import timm
import torch

model = timm.create_model("resnet18", pretrained=False).cuda().eval()
with torch.no_grad():
    y = model(torch.zeros(1, 3, 64, 64, device="cuda"))
print("OK", torch.__version__, tuple(y.shape))
