// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

package org.ordec.intellij;

import com.intellij.openapi.fileTypes.LanguageFileType;
import com.intellij.openapi.util.IconLoader;
import org.jetbrains.annotations.NotNull;

import javax.swing.Icon;

/**
 * Native .ord file type, handled by the ORD Python dialect.
 */
public final class OrdFileType extends LanguageFileType {
    public static final OrdFileType INSTANCE = new OrdFileType();

    private OrdFileType() {
        super(OrdLanguage.INSTANCE);
    }

    @Override
    public @NotNull String getName() {
        return "ORD";
    }

    @Override
    public @NotNull String getDescription() {
        return "ORD hardware description language";
    }

    @Override
    public @NotNull String getDefaultExtension() {
        return "ord";
    }

    @Override
    public Icon getIcon() {
        return IconLoader.getIcon("/icons/ord.svg", OrdFileType.class);
    }
}
