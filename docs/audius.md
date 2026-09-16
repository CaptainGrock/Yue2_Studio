# Publish songs to Audius

YuE2 Studio can connect an Audius account and publish completed library songs. End users only sign in to Audius and approve access; they do not create developer apps or enter API keys.

## Maintainer setup

Create one Audius developer app for YuE2 Studio, then register the Studio callback URL. The default local launcher uses:

`http://localhost:7862/`

If Studio uses another port, register that origin with a trailing slash as an additional redirect URI.

Set the developer app's public API key before launching Studio:

```powershell
[Environment]::SetEnvironmentVariable("YUE2_AUDIUS_API_KEY", "your-public-api-key", "User")
```

Open a new terminal or restart the launcher after setting it. For a one-session test:

```powershell
$env:YUE2_AUDIUS_API_KEY="your-public-api-key"
python launch_studio.py
```

Audius documents this API key as safe for frontend use; it is an OAuth client identifier and is visible in browser requests. **Never put the Audius bearer token in Studio, Git, browser code, or release files.**

## User workflow

1. Open **Connected platforms** in the Studio sidebar.
2. Choose **Connect Audius**.
3. Sign in or create an Audius account and approve write access.
4. Confirm publication rights and choose a default genre.
5. Open a completed song in the library and choose **Upload to Audius**.

Studio uploads the lossless FLAC, creates the Audius track, and records the returned track ID and safe public page URL in browser-local storage. Project exports and run artifacts do not contain OAuth tokens.

Only public `https://audius.co/...` links are opened. Audius storage-node and CDN URLs are deliberately rejected so a browser or security product is never directed to raw storage infrastructure.

## Rights and AI-generated music

The uploader must confirm that they have the rights to publish the lyrics, recording, voice, artwork, and samples. Studio identifies the upload as AI-assisted in its description and sets Audius's `noAiUse` metadata flag. This integration does not grant rights to imitate an artist, use an unauthorized voice, or distribute copyrighted source material.

## Implementation notes

- OAuth uses Audius's Authorization Code flow with PKCE and `write` scope.
- The browser SDK is pinned to `@audius/sdk@16.0.0`; an internet connection is required.
- OAuth state is managed by Audius's SDK in the local browser profile.
- Upload history is local to that browser and keyed by the Studio job ID.
- A hosted multi-user deployment should perform a separate security review and use a fixed HTTPS redirect URI.
