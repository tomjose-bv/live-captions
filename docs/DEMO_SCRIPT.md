# 60-second demo script

A screen recording that shows the whole tool in one minute. Record at 1920×1080 with
Windows' Snipping Tool (Win+Shift+R) or OBS. Use a public-domain or your own video as
the audio source; never record a real call without everyone's consent.

**Prep (not recorded):** run `scripts\setup.ps1`, launch the app once and dismiss the consent
notice so the model is downloaded. Open a public-domain talk or audiobook clip in a
browser tab (for example a LibriVox recording). Have a terminal ready in the repo folder.
Optional: install Ollama and `ollama pull llama3.2:3b` to show summaries.

| Time | On screen | Voice-over / caption |
|---|---|---|
| 0:00–0:05 | App window, title bar visible, consent banner at the top | "Live Captions: real-time captions for anything your PC plays — fully offline." |
| 0:05–0:15 | Click **Start**. Banner turns red ("Captioning live…"). Play the clip. Grey interim text appears, then turns black when the speaker pauses. | "It listens to your speakers through WASAPI loopback. Grey text is the live preview; it's finalised when the speaker pauses." |
| 0:15–0:25 | Speak into the mic for a few seconds. A new `You:` line appears under the `Them:` lines. | "Turn on the mic and both sides of a call are labelled: You for the mic, Them for the speakers." |
| 0:25–0:32 | Switch Wi-Fi off from the taskbar (or show Airplane mode) — captions keep coming. | "No cloud. Speech recognition runs on the CPU with Moonshine or faster-whisper." |
| 0:32–0:40 | Click **Stop**, edit a misheard word in the textbox, click **Export…** and save as Markdown. | "The transcript is editable, and nothing is saved unless you export it." |
| 0:40–0:48 | Click **Summarize** — either the summary window (with Ollama) or the friendly "couldn't reach a local LLM" message. | "Optional summaries and action items come from a local LLM such as Ollama. No LLM? The app still works." |
| 0:48–0:58 | Terminal: `livecaptions-bench --limit 10 --engines moonshine:moonshine/tiny,whisper:base.en`; the results table prints. Then scroll the README benchmark table. | "And it ships with a benchmark harness: word error rate, real-time factor and latency for each local engine, measured on LibriSpeech." |
| 0:58–1:00 | Repo URL on screen. | "Open source, MIT licensed." |

**Tips:** raise Windows display scaling to 150% so captions are readable in the video, and
trim any dead time while a model loads.
