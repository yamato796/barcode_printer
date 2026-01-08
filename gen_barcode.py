
import time
import subprocess
from barcode import Code128
from barcode.writer import ImageWriter

while(True):
    #ch="Test Barcode"
    ch = input('scan barcode')
    print(f"{ch}")
    current_timestamp = time.time()
    filename = f"code_{int(current_timestamp)}"
    my_code = Code128(ch, writer=ImageWriter())        
    my_code.save(f"{filename}")

    subprocess.run(["lp", "-o", "fit-to-page", f"./{filename}.png"])
