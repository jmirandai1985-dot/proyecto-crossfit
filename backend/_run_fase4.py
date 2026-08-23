"""Lanza _validar_fase4_e2e_stock.py en background (no bloquea) y escribe el
output a _fase4_out.txt / _fase4_err.txt. Imprime el PID del hijo."""
import os
import subprocess
import sys

env = dict(os.environ)
env["ENVIRONMENT"] = "test"
with open("_fase4_out.txt", "w", encoding="utf-8") as fout, \
        open("_fase4_err.txt", "w", encoding="utf-8") as ferr:
    p = subprocess.Popen(
        [sys.executable, "_validar_fase4_e2e_stock.py"],
        stdout=fout, stderr=ferr, env=env, cwd=os.getcwd(),
    )
print("PID:", p.pid)
