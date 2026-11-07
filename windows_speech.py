"""Optional Windows voices through the same .NET runtime as the desktop window."""
from functools import lru_cache
from pathlib import Path


def synthesizer():
    import clr
    clr.AddReference('System.Speech')
    from System.Speech.Synthesis import SpeechSynthesizer
    return SpeechSynthesizer()


@lru_cache(maxsize=1)
def voice_names():
    try:
        speech = synthesizer()
        try:
            return tuple(v.VoiceInfo.Name for v in speech.GetInstalledVoices()
                         if v.Enabled and str(v.VoiceInfo.Culture.Name).startswith('en-'))
        finally:
            speech.Dispose()
    except Exception as error:
        print('Windows English voices unavailable: %s: %s' % (type(error).__name__, error))
        return ()


def synthesize(turns, out_dir):
    voices = voice_names()
    if not voices:
        return []
    speech = synthesizer()
    speakers, files = {}, []
    try:
        for i, turn in enumerate(turns):
            speaker = turn['speaker'].lower()
            if speaker not in speakers:
                speakers[speaker] = voices[len(speakers) % len(voices)]
            speech.SelectVoice(speakers[speaker])
            path = Path(out_dir).resolve() / ('turn_%02d.wav' % i)
            speech.SetOutputToWaveFile(str(path))
            speech.Speak(turn['text'])
            speech.SetOutputToNull()
            files.append(path.name)
        return files
    finally:
        speech.Dispose()
