# Measurement definitions

## OCR scoring

All published private-photo accuracy numbers are summaries, with the source images
and reference/predicted text withheld. References are human transcriptions of
selected readable blocks. This is a development set, not a blind, representative
test set. Excluded crossed-out text and formula/unit blocks limit the scope.

The normalization used is:

```python
import unicodedata
def normalize(text):
    return ''.join(c for c in unicodedata.normalize('NFC', text).casefold()
                   if c.isalnum())
```

Vietnamese accents remain significant. Character error rate is
`100 * Levenshtein_edits / normalized_reference_characters`. Whitespace and
punctuation are excluded, so these are not raw-text CER numbers.

- **Document A:** global Levenshtein distance between the concatenated selected
  reference blocks and selected prediction blocks.
- **Document B, strict:** score each supplied region against its assigned reference.
- **Document B, aligned:** global reference / local prediction alignment, allowing
  free leading/trailing predicted context. This reduces penalties for neighboring
  text inside an overlapping crop. Each reference block is matched independently;
  this is not a constrained whole-page alignment or a measure of layout accuracy.
- **Filtered-input check:** the same fixed reference subsets are aligned within
  each complete filtered-input OCR output and their edit counts are summed.

The local-alignment dynamic program starts its first row at zero and returns the
minimum entry of its last row; insertions/deletions/substitutions inside the match
are still charged. Cropped recognizers use external layout boxes, so their CER
and latency do not constitute complete independent document systems.

## Image metrics

Synthetic image metrics compare RGB/BGR pixel arrays at the same resolution:

- PSNR: `10 * log10(255**2 / max(mean_squared_error, 1e-10))`.
- SSIM: scikit-image structural similarity, channel axis 2, data range 255.
- Dark-stroke recall: reference grayscale `< 200`; fraction also `< 200` in output.
- Background deviation: standard deviation of output grayscale on other pixels.

Dark-stroke recall is a threshold-based proxy, not recognized-character accuracy.
It cannot detect every erased mark or invented character. The reference contains
a green bar, so grayscale conversion is penalized by color PSNR. All three
synthetic lighting variants originate from a single generated page.

For the included case-0 images, recompute these metrics in an isolated environment:

```bash
python -m venv .venv-metrics
.venv-metrics/bin/pip install numpy==1.26.4 opencv-python-headless==4.11.0.86 scikit-image==0.24.0
.venv-metrics/bin/python experiments/evaluate_images.py \
  experiments/assets/synthetic-clean.png \
  experiments/assets/synthetic-0-docres_appearance.png
```

The included PNGs are unmodified frozen synthetic outputs. They illustrate one
condition and do not make the private-photo experiments publicly reproducible.

## Geometry

Corner IoU compares a predicted quadrilateral with the generated paper polygon.
Twelve deterministic generated cases use seed 2411 and add perspective, lighting,
occlusion and blur to one page. The earlier preprocessing mistake is not included
in the released aggregate corner scores.

Dewarp fold fractions count non-positive local grid Jacobians on each model's
sampled mapping. UVDoc uses a 45×31 grid; DocRes uses a smoothed 256×256 mapping.
These resolutions, and the GPUs used, differ. Fold detection is a sanity check,
not a shared geometric-error metric or proof of perfect rectification.

## Runtime and memory

Most per-model inference timings exclude downloads, imports and model loading.
Restoration timings include their specified transfer/postprocessing; some first
shapes include warmup. Region timings exclude external layout unless explicitly
stated. PyTorch peak allocations exclude some CUDA/driver reservations and may
be the maximum across several cases in a process. Do not interpret them as the
minimum GPU capacity needed for the complete application.

Native Paddle FP32, BF16 recognizers, int8 Qwen and FP16 restoration are distinct
conditions. The separate total-device VRAM idle test is operational telemetry,
not directly comparable with Torch allocation figures.

## Availability and deployment

Only PaddleOCR-VL-1.6, DocQuadNet, UVDoc, DocRes and the CPU DocShadow adaptation
are part of the current application. Experimental Chandra, MonkeyOCR, SenOCR,
Qwen, PhaSR and DocRes+MBD results are retained as development evidence, not as
claims that those models are installed or supported presets in the release.
