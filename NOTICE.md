# Third-party components

The MIT license in this repository covers TailScan code. Model weights and
third-party source downloaded during setup are separate and retain their upstream
licenses. We do not redistribute pretrained weights in Git or in the IPA.

| Component | Use | Upstream |
| --- | --- | --- |
| PaddleOCR / PaddleOCR-VL-1.6 | Document layout and OCR | [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR), [model](https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6) |
| DocRes | Appearance enhancement; original-resolution gain adaptation | [Official implementation](https://github.com/ZZZHANG-jx/DocRes) |
| UVDoc | Backward-grid document dewarping | [Official implementation](https://github.com/tanguymagne/UVDoc) |
| DocShadow | Document shadow removal; smooth gain adaptation | [Original model](https://github.com/CXH-Research/DocShadow-SD7K), [ONNX implementation linked by the authors](https://github.com/fabio-sim/DocShadow-ONNX-TensorRT) |
| MakeACopy / DocQuadNet | Automatic document corner suggestions | [MakeACopy](https://github.com/egdels/makeacopy) |
| DejaVu Sans | Searchable PDF text | [DejaVu fonts](https://dejavu-fonts.github.io/) |

Core libraries include FastAPI, PaddlePaddle, PyTorch, ONNX Runtime, OpenCV, Pillow,
ReportLab, NumPy and Apple's UIKit/WebKit. See their respective distribution terms.
The model bootstrap script pins revisions and verifies SHA-256 hashes for auxiliary
weights. Downloaded source license files are saved next to model assets where
available. Review upstream terms when using or redistributing those assets.

TailScan's filters, dewarping and OCR are adaptations for this application, not
official benchmark implementations or a claim of state-of-the-art accuracy.
