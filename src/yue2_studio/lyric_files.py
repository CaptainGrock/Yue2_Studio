"""Shared matching rules for dataset lyrics and Artist Trainer."""


def matching_lyrics(audio, preferred='.lyrics.txt'):
    if preferred not in ('.lyrics.txt', '.txt'):
        raise ValueError('Unsupported lyric suffix.')
    alternate = '.txt' if preferred == '.lyrics.txt' else '.lyrics.txt'
    paths = [audio.with_suffix(preferred), audio.with_suffix(alternate)]
    return next((path for path in paths if path.exists() or path.is_symlink()), paths[0])
