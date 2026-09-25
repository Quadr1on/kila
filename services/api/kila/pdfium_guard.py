"""PDFium is not thread-safe. Every pypdfium2 call in the process must hold this lock.

Found the hard way: a thumbnail render on a request thread racing the OCR worker's page render
crashed with an access violation. Hold it only around PDFium calls (open / text / render /
close), never around OCR or model inference.
"""

import threading

PDFIUM_LOCK = threading.RLock()
