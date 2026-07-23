// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

package org.ordec.intellij;

import com.intellij.lang.Language;
import com.jetbrains.python.PythonLanguage;

/**
 * ORD as a Python dialect: everything that is plain Python is inherited
 * from the Python plugin, only the ORD delta (mirroring ordec/ord/ord.lark)
 * is added. PythonLanguage is final, so the dialect registers through the
 * base-language mechanism, which is what the Python plugin's dialect
 * machinery keys on (Language.isKindOf).
 */
public final class OrdLanguage extends Language {
    public static final OrdLanguage INSTANCE = new OrdLanguage();

    private OrdLanguage() {
        super(PythonLanguage.getInstance(), "ORD");
    }
}
