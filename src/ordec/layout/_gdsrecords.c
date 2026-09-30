// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

// C implementation of scan() and read_structure() of ordec.layout.gdsrecords;
// see there for the interface. gdsrecords.py holds an equivalent (slow)
// pure-Python implementation, used when this extension is not built.
//
// A GDS file is a sequence of records. Each record starts with a 4-byte
// header: total record length (uint16, big endian, including the header),
// record type, data type.

#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <stdint.h>
#include <string.h>
#include <math.h>

enum {
    UNITS = 0x03, ENDLIB = 0x04, STRNAME = 0x06, ENDSTR = 0x07,
    BOUNDARY = 0x08, LAYER = 0x0D, DATATYPE = 0x0E, XY = 0x10, ENDEL = 0x11,
};

enum {DT_NONE = 0, DT_BITARRAY = 1, DT_INT16 = 2, DT_INT32 = 3, DT_REAL8 = 5, DT_ASCII = 6};

static int16_t be_int16(const uint8_t *p) {
    return (int16_t)(((uint16_t)p[0] << 8) | p[1]);
}

static int32_t be_int32(const uint8_t *p) {
    return (int32_t)(((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) | ((uint32_t)p[2] << 8) | p[3]);
}

// GDS real8: sign bit, 7-bit excess-64 exponent to base 16, 56-bit mantissa
// (a fraction, binary point left of the mantissa).
static double be_real8(const uint8_t *p) {
    uint64_t mantissa = 0;
    for (int i = 1; i < 8; i++)
        mantissa = (mantissa << 8) | p[i];
    double v = ldexp((double)mantissa, 4 * ((p[0] & 0x7f) - 64) - 56);
    return (p[0] & 0x80) ? -v : v;
}

// Returns the length of the record at pos, or -1 with exception set if the
// record does not fit between pos and end.
static Py_ssize_t record_len(const uint8_t *data, Py_ssize_t pos, Py_ssize_t end) {
    if (end - pos >= 4) {
        Py_ssize_t len = ((Py_ssize_t)data[pos] << 8) | data[pos + 1];
        if (len >= 4 && len <= end - pos)
            return len;
    }
    PyErr_Format(PyExc_ValueError, "Invalid GDS data: bad record at offset %zd.", pos);
    return -1;
}

// Decodes the payload of a record to a Python object: bytes for strings,
// else a number for a single value, a tuple for multiple values.
static PyObject *record_value(const uint8_t *rec, Py_ssize_t len) {
    const uint8_t *p = rec + 4;
    Py_ssize_t size, n = len - 4;
    switch (rec[3]) {
    case DT_ASCII:
        while (n > 0 && p[n - 1] == 0) // strings are NUL-padded to even length
            n--;
        return PyBytes_FromStringAndSize((const char *)p, n);
    case DT_BITARRAY:
    case DT_INT16: size = 2; break;
    case DT_INT32: size = 4; break;
    case DT_REAL8: size = 8; break;
    default:
        Py_RETURN_NONE;
    }
    Py_ssize_t count = n / size;
    PyObject *tuple = PyTuple_New(count);
    if (!tuple)
        return NULL;
    for (Py_ssize_t i = 0; i < count; i++, p += size) {
        PyObject *v;
        if (rec[3] == DT_BITARRAY)
            v = PyLong_FromLong((uint16_t)be_int16(p));
        else if (rec[3] == DT_INT16)
            v = PyLong_FromLong(be_int16(p));
        else if (rec[3] == DT_INT32)
            v = PyLong_FromLong(be_int32(p));
        else
            v = PyFloat_FromDouble(be_real8(p));
        if (!v) {
            Py_DECREF(tuple);
            return NULL;
        }
        PyTuple_SET_ITEM(tuple, i, v);
    }
    if (count == 1) {
        PyObject *v = Py_NewRef(PyTuple_GET_ITEM(tuple, 0));
        Py_DECREF(tuple);
        return v;
    }
    return tuple;
}

static PyObject *scan(PyObject *self, PyObject *args) {
    Py_buffer buf;
    if (!PyArg_ParseTuple(args, "y*", &buf))
        return NULL;
    const uint8_t *data = buf.buf;
    PyObject *units = Py_NewRef(Py_None), *structures = PyList_New(0), *name = NULL;
    Py_ssize_t pos = 0, start = 0;
    if (!structures)
        goto fail;
    while (pos < buf.len) {
        Py_ssize_t len = record_len(data, pos, buf.len);
        if (len < 0)
            goto fail;
        uint8_t rt = data[pos + 2];
        if (rt == ENDLIB) // may be followed by padding
            break;
        if (rt == UNITS) {
            Py_SETREF(units, record_value(data + pos, len));
            if (!units)
                goto fail;
        } else if (rt == STRNAME) {
            Py_XSETREF(name, record_value(data + pos, len));
            if (!name)
                goto fail;
            start = pos + len;
        } else if (rt == ENDSTR && name) {
            PyObject *item = Py_BuildValue("(Onn)", name, start, pos);
            Py_CLEAR(name);
            if (!item)
                goto fail;
            int err = PyList_Append(structures, item);
            Py_DECREF(item);
            if (err)
                goto fail;
        }
        pos += len;
    }
    Py_XDECREF(name);
    PyBuffer_Release(&buf);
    return Py_BuildValue("(NN)", units, structures);
fail:
    Py_XDECREF(units);
    Py_XDECREF(structures);
    Py_XDECREF(name);
    PyBuffer_Release(&buf);
    return NULL;
}

// Builds the (kind, {record type: value}) tuple of the element whose
// records lie between pos and end (ENDEL excluded).
static PyObject *element(const uint8_t *data, Py_ssize_t pos, Py_ssize_t end) {
    int kind = data[pos + 2];
    PyObject *records = PyDict_New();
    if (!records)
        return NULL;
    while (pos < end) {
        Py_ssize_t len = ((Py_ssize_t)data[pos] << 8) | data[pos + 1]; // validated by caller
        if (data[pos + 3] != DT_NONE) {
            PyObject *key = PyLong_FromLong(data[pos + 2]);
            PyObject *value = record_value(data + pos, len);
            int err = (!key || !value) ? -1 : PyDict_SetItem(records, key, value);
            Py_XDECREF(key);
            Py_XDECREF(value);
            if (err) {
                Py_DECREF(records);
                return NULL;
            }
        }
        pos += len;
    }
    return Py_BuildValue("(iN)", kind, records);
}

static PyObject *read_structure(PyObject *self, PyObject *args) {
    Py_buffer buf;
    Py_ssize_t pos, end;
    if (!PyArg_ParseTuple(args, "y*nn", &buf, &pos, &end))
        return NULL;
    const uint8_t *data = buf.buf;
    int32_t *quads = NULL; // 12 values per quad
    Py_ssize_t quads_len = 0, quads_cap = 0;
    PyObject *elements = PyList_New(0);
    if (!elements)
        goto fail;
    if (pos < 0 || end > buf.len) {
        PyErr_SetString(PyExc_ValueError, "structure range outside of data");
        goto fail;
    }
    while (pos < end) {
        // First pass over the element's records: find its ENDEL and note
        // what is needed to recognize a quad.
        Py_ssize_t elem_start = pos;
        const uint8_t *layer = NULL, *datatype = NULL, *xy = NULL;
        for (;;) {
            if (pos >= end) {
                PyErr_SetString(PyExc_ValueError, "Invalid GDS data: element without ENDEL.");
                goto fail;
            }
            Py_ssize_t len = record_len(data, pos, end);
            if (len < 0)
                goto fail;
            uint8_t rt = data[pos + 2];
            if (rt == ENDEL)
                break;
            if (rt == LAYER && len == 6)
                layer = data + pos + 4;
            else if (rt == DATATYPE && len == 6)
                datatype = data + pos + 4;
            else if (rt == XY && len == 44)
                xy = data + pos + 4;
            pos += len;
        }
        if (data[elem_start + 2] == BOUNDARY && layer && datatype && xy) {
            if (quads_len == quads_cap) {
                quads_cap = quads_cap ? 2 * quads_cap : 1024;
                int32_t *grown = PyMem_Realloc(quads, quads_cap * 12 * sizeof(int32_t));
                if (!grown) {
                    PyErr_NoMemory();
                    goto fail;
                }
                quads = grown;
            }
            int32_t *q = quads + 12 * quads_len++;
            q[0] = be_int16(layer);
            q[1] = be_int16(datatype);
            for (int i = 0; i < 10; i++)
                q[2 + i] = be_int32(xy + 4 * i);
        } else if (pos > elem_start) {
            PyObject *item = element(data, elem_start, pos);
            if (!item)
                goto fail;
            int err = PyList_Append(elements, item);
            Py_DECREF(item);
            if (err)
                goto fail;
        }
        pos += 4; // ENDEL
    }
    PyObject *quads_bytes = PyBytes_FromStringAndSize((const char *)quads, quads_len * 12 * sizeof(int32_t));
    if (!quads_bytes)
        goto fail;
    PyMem_Free(quads);
    PyBuffer_Release(&buf);
    return Py_BuildValue("(NN)", quads_bytes, elements);
fail:
    PyMem_Free(quads);
    Py_XDECREF(elements);
    PyBuffer_Release(&buf);
    return NULL;
}

static PyMethodDef methods[] = {
    {"scan", scan, METH_VARARGS, NULL},
    {"read_structure", read_structure, METH_VARARGS, NULL},
    {NULL, NULL, 0, NULL},
};

static struct PyModuleDef module = {
    PyModuleDef_HEAD_INIT, "_gdsrecords", NULL, -1, methods,
};

PyMODINIT_FUNC PyInit__gdsrecords(void) {
    return PyModule_Create(&module);
}
