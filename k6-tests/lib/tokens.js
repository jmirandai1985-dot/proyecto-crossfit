// Tokens de los 500 alumnos LOAD_TEST (generados por _seed_load_test.py)
// Nota: open() resuelve relativo a ESTE archivo (lib/), por eso '../'.
const raw = JSON.parse(open('../tokens.json'));

export const tokens = raw;
