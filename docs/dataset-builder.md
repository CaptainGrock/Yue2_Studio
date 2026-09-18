# Dataset Builder: playlist audio and lyrics

## Add song structure

Open **3. Add song structure → Load saved lyrics**. Configure your existing LLM Runner, then approve sending lyric text and artist/title context to that runner. Cloud requests may incur charges; local runners may consume the same GPU memory needed for music tasks. No audio is uploaded for this step.

Suggest structure for one song or all untagged songs. Requests use the Runner's existing provider, model, output-token limit, temperature and timeout, and share its concurrency lock. Credentials remain request-scoped. Files with recognized section tags are skipped, not relabeled.

The dedicated instruction asks for JSON section labels and original line numbers, not rewritten lyrics. Studio validates labels and boundaries and inserts tags into the original lines itself. Words, punctuation, repetitions and original line order remain unchanged. Invalid or truncated responses are rejected. Text-only inference is not an audio-verified structure analysis.

Compare the original and proposed text, check **I reviewed this proposed structure**, then apply individually or use **Apply all reviewed suggestions**. Applying preserves an exact original-byte backup under the dataset's `.lyrics-backups` directory before replacing the existing matching lyric file. Stale suggestions are rejected if the file or matching filename has changed. Files remain unchanged until Apply.

Stop or close the panel to stop after the current operation. Reload discards unapplied suggestions. Rescan Artist Trainer and save a new setup after applying tags, because saved setups contain lyric snapshots and hashes. This does not change a running training job.

Open **Studio Tools → Dataset Builder**. Paste a public/unlisted YouTube playlist URL and enter an absolute output folder, then choose **Download playlist as WAV**. Use recordings you own or have permission to download/use.

For a single-artist playlist with song-only titles, enter the optional **Fallback artist / band**. Artist metadata takes priority, followed by an inferred Artist - Song title, then your fallback. Existing artist names are not overwritten or duplicated. Title parsing is heuristic; review inferred filenames, especially song titles containing hyphens. Changing the fallback does not rename previously completed downloads.

Requirements: `yt-dlp[default]` in Studio's Python environment, FFmpeg and ffprobe on PATH, and Node.js 22+ or Deno 2.3+ on PATH. A private Windows Node distribution extracted under `tools/dataset-runtime/node-*/node.exe` is also detected, without changing system PATH. **Install / update downloader** installs the Python package; it does not install FFmpeg or Node/Deno. Restart Studio after installing a runtime or changing PATH.

Imports use a separate CPU worker, not the GPU queue. Output is 48 kHz stereo PCM16 WAV; transcoding does not restore quality lost in the source. Artist/track metadata takes priority over parsing video titles. Missing or inferred metadata is flagged for review. Filenames are Windows-safe; collisions gain the video ID and never overwrite an existing file.

The output folder's `.playlist-import/manifest.json` records artist, title, album, duration, source URL, filename and size for later dataset stages. Do not remove it if you want verified skipping. Cancel preserves completed WAVs. Restart with the same playlist/folder to skip completed files and retry others. Partial downloads are kept inside `.playlist-import`; no automatic deletion of user files occurs.

Progress and per-track errors appear in the panel. Closing the panel does not cancel. Worker/installation logs are in `runs/dataset-imports/<id>/run.log`. Closing the last browser tab lets an active import finish before Studio exits. Stopping the server explicitly cancels it.

Download limitations: no authentication/cookie import, no restricted videos or live streams, no automatic handling of YouTube bot checks. Do not run two Studio instances importing into the same folder simultaneously. WAVs can require significant disk space (about 11.5 MB/minute).

## Get lyrics

In the same window, select **2. Get lyrics**, enter the existing dataset folder, and click **Load songs**. The tool reads WAV filenames, saved playlist metadata, and WAV duration. Check or edit artist/title fields before searching; edits affect the search, not the audio filenames.

**Search missing lyrics** queries [LRCLIB's documented API](https://lrclib.net/docs) at `GET /api/search` with `artist_name` and `track_name`. No API key or new package is required. Audio is not uploaded. Searches run sequentially; errors appear per song, and rate limiting stops the batch. Stop or close the panel to stop after the current request. Page reload discards unsaved results.

LRCLIB returns at most 20 candidates. The tool ranks exact artist/title matches first, then the closest duration. Select a result using its artist, title, album and duration; ranking is not proof of lyric accuracy. Review the retrieved lyrics, then click **Save reviewed lyrics** for that song or **Save all selected matches** for the whole queue. Bulk save uses each currently selected result, skips existing/empty/instrumental entries, reports failures individually, and continues to the next song. Stop or close the panel to stop after the current save. Search alone never saves. Instrumental or empty records cannot be saved through the review UI.

Output uses the WAV's exact basename with a `.lyrics.txt` extension, matching the trainer default. Both matching `.lyrics.txt` and `.txt` files are recognized and never overwritten. Artist Trainer automatically accepts either format; the chosen suffix takes priority if both exist, with `.lyrics.txt` preferred by default. Saved lyrics must fit the trainer's 64 KB per-file limit. Plain lyrics are preferred; if only synchronized lyrics exist, timestamps are stripped. No LLM rewriting, correction, or section generation occurs at this stage. Use lyrics you have permission to use.

Numbered upload titles such as `02   Song - Album` use the supplied fallback artist instead of treating the track number and song name as an artist. Other title parsing remains heuristic and should be reviewed.
