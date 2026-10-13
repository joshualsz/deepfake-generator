# Audio deepfake detection dataset: voice cloning, pass 1

**49 cloned clips + 49 real recordings** of the same sentences by the same 10 speakers.
Generator: CosyVoice-300M (zero-shot voice cloning), repo QwenAudio/CosyVoice @ 074ca6dc.

## How each pair was made
For each speaker: one **reference** recording (the voice prompt) + 5 **target** sentences.
- **fake**: CosyVoice clones the speaker from the reference clip and says the target sentence
- **real**: the speaker's own VCTK recording of that same target sentence

So every fake has a real twin with identical speaker and words, and the only difference is real vs. cloned.

## Layout
```
real/<speaker>_<text_id>_mic1.flac          original VCTK recordings (48 kHz FLAC, silence-trimmed)
fake/cosyvoice-300m/<pair_id>.wav           cloned clips (22.05 kHz WAV)
normalized/{real,fake/cosyvoice-300m}/*.wav same clips, all 16 kHz mono 16-bit WAV  <- train on these
quarantine/                                 generated but excluded (failed QA)
manifest.jsonl                              one row per generation attempt (text, speaker, prompt, sha256, status, ...)
qa_cosyvoice-300m.json                      per-clip QA (Whisper transcript/WER, speaker similarity)
```
Inputs: `inputs/voices/` (clips + manifest), `inputs/audio_pairs.json` (pairs a000-a049).

## QA (no human listening; automatic checks)
| check | cloned | real |
|---|---|---|
| Whisper word error rate vs. target sentence | 6.6% | 6.1% |
| CAM++ speaker ID: clone matched to the right speaker (of 10) | 98% | - |
| speaker similarity: own speaker / other speakers | 0.596 / 0.32 | 0.739 (real vs. real, same speaker) |

Clips with WER > 0.4 were regenerated (up to 3 rounds). `a044` ("The proposal was rejected.") stayed garbled and is quarantined.
Remaining small "errors" are mostly ASR spelling (underway / under way).

## Speakers (VCTK 0.92, mic1)
| speaker | gender | age | accent | region |
|---|---|---|---|---|
| p231 | F | 23 | English | Southern England |
| p244 | F | 22 | English | Manchester |
| p255 | M | 19 | Scottish | Galloway |
| p265 | F | 23 | Scottish | Ross |
| p276 | F | 24 | English | Oxford |
| p286 | M | 23 | English | Newcastle |
| p301 | F | 23 | American | North Carolina |
| p313 | F | 24 | Irish | County Down |
| p335 | F | 25 | NewZealand | English |
| p361 | F | 19 | American | New Jersey |

Source: VCTK Corpus 0.92 (CSTR, University of Edinburgh) - speakers consented to research use. https://datashare.ed.ac.uk/handle/10283/3443. License: CC BY 4.0 (attribution: Yamagishi, Veaux, MacDonald, CSTR VCTK Corpus 0.92). Fetched via https://huggingface.co/datasets/sanchit-gandhi/vctk (via datasets-server rows API).

## Caveats
- **Use `normalized/` for training.** Originals differ in sample rate and format (48 kHz FLAC vs 22.05 kHz WAV), which a detector
  would learn as a shortcut. Loudness and leading/trailing silence also differ; consider loudness-normalising and trimming too.
- **Gender imbalance:** 8 female / 2 male speakers (sampled by position in the corpus). Balance it in the next pass.
- **One generator, one model size.** CosyVoice-300M only; the larger CosyVoice2/3 models were skipped (single files > 2 GB).
- **Small.** 49 pairs is a pipeline check. Scale with `scripts/fetch_vctk.py --speakers N --per-speaker M` (writes new pairs; existing
  outputs are skipped by pair_id only if the pairs file is unchanged, so fetch into a new pairs file for a second batch).
- **Consent:** VCTK speakers agreed to research use. Never clone a real person's voice without consent.
