"""Turn the rendered frames into the README GIFs and stills (needs Pillow)."""
import glob
import os

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "_raw")
OUT = os.path.join(HERE, "..")
BG, FG = (14, 15, 19), (232, 232, 236)


def font(size):
    for p in ("C:/Windows/Fonts/segoeuib.ttf", "/System/Library/Fonts/Helvetica.ttc",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def gif(folder, out, ms, width=640):
    frames = []
    for path in sorted(glob.glob(os.path.join(RAW, folder, "*.png"))):
        im = Image.open(path).convert("RGB")
        im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
        frames.append(im.quantize(colors=192, method=Image.Quantize.MEDIANCUT,
                                  dither=Image.Dither.FLOYDSTEINBERG))
    frames[0].save(os.path.join(OUT, out), save_all=True, append_images=frames[1:],
                   duration=ms, loop=0, optimize=True, disposal=1)
    size = os.path.getsize(os.path.join(OUT, out)) / 1e6
    print(f"{out}: {len(frames)} frames, {size:.1f} MB")


def label(img, text):
    d = ImageDraw.Draw(img)
    f = font(30)
    w = d.textlength(text, font=f)
    d.rounded_rectangle((24, 24, 24 + w + 32, 24 + 52), radius=12, fill=(0, 0, 0))
    d.text((40, 31), text, font=f, fill=FG)
    return img


# Animations: 2-frame steps of a 30 fps timeline -> ~66 ms per GIF frame.
gif("anim_main", "explode.gif", 66)
gif("anim_side", "explode_side.gif", 66)
gif("anim_orbit", "orbit.gif", 60)

# Stills
hero = Image.open(os.path.join(RAW, "hero_exploded.png")).convert("RGB")
hero.save(os.path.join(OUT, "exploded.jpg"), quality=92)
assembled = Image.open(os.path.join(RAW, "hero_assembled.png")).convert("RGB")
assembled.save(os.path.join(OUT, "assembled.jpg"), quality=92)

w, h = 800, 500
pair = Image.new("RGB", (w * 2 + 48, h + 32), BG)
pair.paste(label(assembled.resize((w, h), Image.LANCZOS), "Assembled"), (16, 16))
pair.paste(label(hero.resize((w, h), Image.LANCZOS), "One click later"), (w + 32, 16))
pair.save(os.path.join(OUT, "before_after.jpg"), quality=90)
print("COMPOSE_OK")
