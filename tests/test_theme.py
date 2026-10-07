import pytest

from src.theme import PALETTES


def luminance(color):
    components = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in components]
    return sum(v * weight for v, weight in zip(linear, [.2126, .7152, .0722]))


def contrast(first, second):
    low, high = sorted([luminance(first), luminance(second)])
    return (high + .05) / (low + .05)


@pytest.mark.parametrize('mode', ['Claro', 'Escuro'])
def test_text_caption_and_contact_buttons_have_readable_contrast(mode):
    palette = PALETTES[mode]
    for foreground in ['text', 'muted', 'accent']:
        for background in ['bg', 'surface']:
            assert contrast(palette[foreground], palette[background]) >= 4.5
    assert contrast('#FFFFFF', palette['action']) >= 4.5
