# Third-party code notices

The Oobleck VAE and SnakeBeta implementation in `modeling_vae.py` is derived
from stable-audio-tools commit `a6ae0cdf8b2eb1567a4b42ceadddec3712d99d45`.
The module hierarchy, weight normalization and activation equations preserve
the checkpoint's original inference implementation.

- Oobleck / stable-audio-tools: Copyright (c) 2023 Stability AI, MIT.
  Full text: `licenses/stable-audio-tools-MIT.txt`.
- SnakeBeta / BigVGAN: Copyright (c) 2022 NVIDIA CORPORATION, MIT.
  Full text: `licenses/SnakeBeta-NVIDIA-MIT.txt`.

These notices cover the identified source code and retain its original licenses.
The YuE2 model checkpoint weights are separately licensed under CC BY-NC 4.0;
see MODEL_LICENSE for the scope and full terms. This does not relicense third-party code.

## Pipeline source attribution

`src/yue2/pipeline.py` is derived from the Apache-2.0 YuE2 runtime by the
YuE2 authors, upstream commit `92a73cc7652fcc1f937855e4b765e0a0edd7ff2e`:
https://github.com/multimodal-art-projection/YuE

Studio modifications add acoustic LoRA selection, per-operation locking,
temporary synthesis-time adapter application, and adapter provenance.
The repository's Apache-2.0 LICENSE applies to these code contributions.
Model weights and dependencies retain their own licenses. No model weights or
community trainer code are bundled with this feature.
