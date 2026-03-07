Installation
============

Requirements
------------

- Python 3.10 or newer
- `Ollama <https://ollama.ai>`_ running locally with a supported model
- Tesseract OCR *(optional — used as a fallback when PaddleOCR times out)*

Install from PyPI
-----------------

.. code-block:: bash

   pip install finamt

Optional extras
~~~~~~~~~~~~~~~

Install the web UI backend (FastAPI + Uvicorn):

.. code-block:: bash

   pip install "finamt[ui]"

Install development tools:

.. code-block:: bash

   pip install "finamt[dev]"

Install documentation tools:

.. code-block:: bash

   pip install "finamt[docs]"

Setting up Ollama
-----------------

.. code-block:: bash

   # macOS / Linux
   curl -fsSL https://ollama.ai/install.sh | sh

   # Pull the recommended model
   ollama pull qwen2.5:7b-instruct-q4_K_M

The library targets **qwen2.5:7b-instruct-q4_K_M** by default — it provides a
good balance between accuracy and speed on a laptop CPU. Any Ollama-compatible
model can be used; see :doc:`configuration` for details.

Installing Tesseract (optional)
--------------------------------

.. code-block:: bash

   # macOS
   brew install tesseract tesseract-lang

   # Ubuntu / Debian
   sudo apt install tesseract-ocr tesseract-ocr-deu

Tesseract is only invoked if PaddleOCR fails or exceeds its timeout, so it is
not required for most use cases.
