# 8-bit-style Kokoro samples

All samples process `../preview.wav`: “Pi agent in Herdr Audio needs food badly!”
Voice: `am_michael`, natural speed. Pitch and duration are unchanged.
Live plugin settings were not changed. Nothing is played automatically.

| File | Treatment | FFmpeg filter (before final limiter) |
| --- | --- | --- |
| `01-light.wav` | Subtle 8-bit grain, full bandwidth | `acrusher=bits=8:mix=0.35` |
| `02-medium.wav` | Narrower arcade-speech sound, stronger 8-bit grain | `aresample=11025,acrusher=bits=8:mix=0.75,aresample=22050` |
| `03-heavy.wav` | More obvious lo-fi crunch: downsampled to 8 kHz, 6-bit grain | `aresample=8000,acrusher=bits=6:mix=0.65,aresample=22050` |
| `04-crisp-crunch.wav` | Full original bandwidth, stronger 5-bit grain; no downsampling | `acrusher=bits=5:mix=0.8` |
| `05-extra-crunch.wav` | Full original bandwidth, 4-bit grain at 90% mix; no downsampling | `acrusher=bits=4:mix=0.9` |
| `06-max-crunch.wav` | Full original bandwidth, 3-bit grain at 95% mix; no downsampling | `acrusher=bits=3:mix=0.95` |

For samples 01–06, each filter ends with `alimiter=limit=0.95:level=false:latency=true`.
Those files are mono, 22,050 Hz, 16-bit PCM WAV for playback compatibility;
“8-bit” refers to the simulated sound, not their WAV storage format.

From the project directory:

```sh
paplay preview.wav                 # Clean reference
paplay samples/01-light.wav
paplay samples/02-medium.wav
paplay samples/03-heavy.wav
paplay samples/04-crisp-crunch.wav
paplay samples/05-extra-crunch.wav
paplay samples/06-max-crunch.wav
```

## Sampled-dialogue versions (07–09)

These use actual mono unsigned 8-bit PCM WAV storage, with no reverb, echo,
added noise, or dither. Tanh soft saturation and band-limiting precede final
peak normalization and quantization. Peaks are approximately -1 dBFS, with
headroom for quantization. The original `preview.wav` is preserved.

| File | Sample rate | Amplitude resolution | Treatment |
| --- | --- | --- | --- |
| `07-sampled-subtle.wav` | 8 kHz | 8-bit | 2× saturation drive, roughly 300–3,400 Hz |
| `08-sampled-medium.wav` | 8 kHz | 8-bit | 3× saturation drive, additional 6-bit crunch at 25% mix, roughly 300–3,400 Hz |
| `09-sampled-heavy.wav` | 6 kHz | 4-bit quantization in an 8-bit container | 4× saturation drive, roughly 300–2,700 Hz |

At 6 kHz, the Nyquist limit is 3 kHz, so the heavy version's low-pass cutoff is
2.7 kHz rather than 3.4 kHz. Its samples occupy a 4-bit quantization grid
(at most 16 amplitude levels); standard linear PCM WAV has no 4-bit container.

```sh
paplay samples/07-sampled-subtle.wav
paplay samples/08-sampled-medium.wav
paplay samples/09-sampled-heavy.wav
```

Regenerate these three files and run their built-in checks with
`python3 samples/make_sampled.py` (overwrites only samples 07–09).
Checks cover WAV format, duration, peak headroom, amplitude resolution, and
preservation of the source file. Live plugin settings remain unchanged.
