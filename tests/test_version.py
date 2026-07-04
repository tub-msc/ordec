# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import ordec.version


def test_doc_url_release(monkeypatch):
    monkeypatch.setattr(ordec.version, 'version', '0.6.0')
    assert ordec.version.doc_url('webui.html') == \
        'https://ordec.readthedocs.io/en/v0.6.0/webui.html'


def test_doc_url_dev(monkeypatch):
    monkeypatch.setattr(ordec.version, 'version', '0.7.0.dev5+g123abc')
    assert ordec.version.doc_url() == \
        'https://ordec.readthedocs.io/en/latest/'


def test_doc_url_unknown(monkeypatch):
    monkeypatch.setattr(ordec.version, 'version', 'unknown')
    assert ordec.version.doc_url() == \
        'https://ordec.readthedocs.io/en/latest/'
