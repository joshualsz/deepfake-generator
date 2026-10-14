"""Stand-in for the repo's entry point: needs CUDA torch."""
import torch

x = torch.ones(2, 2).cuda()
print("OK", torch.__version__, torch.version.cuda, (x @ x).sum().item())
