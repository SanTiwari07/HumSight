import sys, glob
from PIL import Image
files = sorted(glob.glob(sys.argv[1] + "/*.jpg")); cols = int(sys.argv[3]) if len(sys.argv) > 3 else 3
w, h = 800, 450; rows = (len(files) + cols - 1) // cols
S = Image.new("RGB", (cols * w, rows * h), "black")
for i, f in enumerate(files): S.paste(Image.open(f).resize((w, h)), ((i % cols) * w, (i // cols) * h))
S.save(sys.argv[2], quality=88)
