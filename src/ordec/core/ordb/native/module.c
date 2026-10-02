// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

// Module globals, _setup and PyInit__ordb.

#include "module.h"

PyObject *OrdbException, *QueryException;
PyObject *g_check_cb, *g_updater_cls;
PyObject *g_pathnode_mut, *g_pathnode_frz;
PyObject *g_npath_index, *g_npath_child_index;
PyObject *str_ntype, *str_read_hook, *str_refcheck, *str_check_ref,
    *str_factory;
PyTypeObject *NType_Type, *Node_Type, *AttrDesc_Type, *Sg_Type, *Upd_Type,
    *CurIter_Type;

// _setup(**objects): hands base.py's classes and callbacks to the core.
static PyObject *
mod_setup(PyObject *m, PyObject *args, PyObject *kwds)
{
    static char *kwlist[] = {"OrdbException", "QueryException",
        "check_callback", "updater_class", "pathnode_mutable",
        "pathnode_frozen", "npath_index", "npath_child_index", NULL};
    PyObject *v[8] = {NULL};
    PyObject **g[8] = {&OrdbException, &QueryException, &g_check_cb,
        &g_updater_cls, &g_pathnode_mut, &g_pathnode_frz, &g_npath_index,
        &g_npath_child_index};
    if (!PyArg_ParseTupleAndKeywords(args, kwds, "|OOOOOOOO", kwlist, &v[0],
            &v[1], &v[2], &v[3], &v[4], &v[5], &v[6], &v[7]))
        return NULL;
    for (int i = 0; i < 8; i++) {
        if (v[i]) {
            PyObject *old = *g[i];
            *g[i] = Py_NewRef(v[i]);
            Py_XDECREF(old);
        }
    }
    Py_RETURN_NONE;
}

static PyMethodDef mod_methods[] = {
    {"_setup", (PyCFunction)(void (*)(void))mod_setup, METH_VARARGS | METH_KEYWORDS, NULL},
    {"ntuple_new", (PyCFunction)(void (*)(void))mod_ntuple_new,
        METH_VARARGS | METH_KEYWORDS, "NodeTuple.__new__(cls, **values)"},
    {NULL}
};

static struct PyModuleDef moddef = {
    PyModuleDef_HEAD_INIT, "ordec.core.ordb._ordb", NULL, -1, mod_methods
};

PyMODINIT_FUNC
PyInit__ordb(void)
{
    if (store_init() < 0)
        return NULL;
    if (!(NType_Type = (PyTypeObject *)PyType_FromSpec(&ntype_spec))
            || !(Node_Type = (PyTypeObject *)PyType_FromSpec(&node_spec))
            || !(AttrDesc_Type = (PyTypeObject *)PyType_FromSpec(
                &attrdesc_spec))
            || !(Sg_Type = (PyTypeObject *)PyType_FromSpec(&sg_spec))
            || !(Upd_Type = (PyTypeObject *)PyType_FromSpec(&upd_spec))
            || !(CurIter_Type = (PyTypeObject *)PyType_FromSpec(
                &curiter_spec)))
        return NULL;

    str_ntype = PyUnicode_InternFromString("_ntype");
    str_read_hook = PyUnicode_InternFromString("read_hook");
    str_refcheck = PyUnicode_InternFromString("refcheck");
    str_check_ref = PyUnicode_InternFromString("check_ref");
    str_factory = PyUnicode_InternFromString("factory");
    if (!str_ntype || !str_read_hook || !str_refcheck || !str_check_ref
            || !str_factory)
        return NULL;

    PyObject *m = PyModule_Create(&moddef);
    if (!m)
        return NULL;
    if (PyModule_AddObjectRef(m, "NType", (PyObject *)NType_Type) < 0
            || PyModule_AddObjectRef(m, "NodeBase", (PyObject *)Node_Type) < 0
            || PyModule_AddObjectRef(m, "AttrDescriptor",
                (PyObject *)AttrDesc_Type) < 0
            || PyModule_AddObjectRef(m, "SubgraphBase",
                (PyObject *)Sg_Type) < 0
            || PyModule_AddObjectRef(m, "UpdaterBase",
                (PyObject *)Upd_Type) < 0
            || PyModule_AddIntConstant(m, "ENGINE_PAGED", ENGINE_PAGED) < 0
            || PyModule_AddIntConstant(m, "K_INT", K_INT) < 0
            || PyModule_AddIntConstant(m, "K_IVEC", K_IVEC) < 0
            || PyModule_AddIntConstant(m, "K_OBJ", K_OBJ) < 0) {
        Py_DECREF(m);
        return NULL;
    }
    return m;
}
