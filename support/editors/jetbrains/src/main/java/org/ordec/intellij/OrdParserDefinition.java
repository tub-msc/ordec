// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

package org.ordec.intellij;

import com.intellij.extapi.psi.ASTWrapperPsiElement;
import com.intellij.lang.ASTNode;
import com.intellij.lang.PsiParser;
import com.intellij.lexer.Lexer;
import com.intellij.openapi.project.Project;
import com.intellij.psi.FileViewProvider;
import com.intellij.psi.PsiElement;
import com.intellij.psi.PsiFile;
import com.intellij.psi.tree.IFileElementType;
import com.jetbrains.python.PythonParserDefinition;
import com.jetbrains.python.psi.PyElementType;
import com.jetbrains.python.psi.PyFileElementType;
import com.jetbrains.python.psi.impl.PyFileImpl;
import org.jetbrains.annotations.NotNull;

public final class OrdParserDefinition extends PythonParserDefinition {
    // subclassed because the Language-taking constructor is protected
    private static final class OrdFileElementType extends PyFileElementType {
        private OrdFileElementType() {
            super(OrdLanguage.INSTANCE);
        }

        // the stub serializer registry asserts unique ids, so a second file
        // element type must not inherit Python's "python.FILE"
        @Override
        public @NotNull String getExternalId() {
            return "ord.FILE";
        }

        // lets ORD parser changes retrigger .ord indexing independently of
        // the Python plugin's stub version
        @Override
        public int getStubVersion() {
            return super.getStubVersion() + 1;
        }
    }

    private static final IFileElementType FILE = new OrdFileElementType();

    @Override
    public @NotNull Lexer createLexer(Project project) {
        return new OrdLexer();
    }

    @Override
    public @NotNull PsiParser createParser(Project project) {
        return new OrdParser();
    }

    @Override
    public @NotNull IFileElementType getFileNodeType() {
        return FILE;
    }

    @Override
    public @NotNull PsiFile createFile(@NotNull FileViewProvider viewProvider) {
        return new PyFileImpl(viewProvider, OrdLanguage.INSTANCE);
    }

    @Override
    public @NotNull PsiElement createElement(@NotNull ASTNode node) {
        // ORD constructs get generic PSI wrappers for now, typed PSI can
        // come once the dialect grows features beyond parsing
        if (!(node.getElementType() instanceof PyElementType)) {
            return new ASTWrapperPsiElement(node);
        }
        return super.createElement(node);
    }
}
