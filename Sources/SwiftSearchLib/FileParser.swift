//
//  FileParser.swift
//  Sextant
//
//  Created by Mathew Gacy on 3/8/26.
//  Copyright © 2026 Mathew Gacy. All rights reserved.
//

import Foundation
import SwiftParser
import SwiftSyntax
import SyntaxSparrow

/// Parses Swift source files via SyntaxSparrow into owned model types.
///
/// This is the **isolation boundary** for SyntaxSparrow. No SyntaxSparrow types escape this file.
/// All other code operates on `FileOverview`, `Declaration`, and `SymbolEntry`.
public struct FileParser: Sendable {

    public enum Error: Swift.Error, LocalizedError, Sendable {
        case fileUnreadable(path: String, underlying: any Swift.Error)

        public var errorDescription: String? {
            switch self {
            case let .fileUnreadable(path, underlying):
                "Cannot read file: \(path) (\(underlying.localizedDescription))"
            }
        }
    }

    public init() {}

    // MARK: - Public API

    /// Parses a Swift file at the given path into a `FileOverview`.
    ///
    /// - Parameter path: Absolute path to a `.swift` file.
    /// - Returns: A `FileOverview` with all top-level declarations.
    /// - Throws: `FileParser.Error.fileUnreadable` if the file cannot be read.
    public func parseFile(at path: String) throws(Error) -> FileOverview {
        let source: String
        do {
            source = try String(contentsOf: URL(filePath: path), encoding: .utf8)
        } catch {
            throw .fileUnreadable(path: path, underlying: error)
        }
        return parseSource(source, file: path)
    }

    /// Parses a Swift source string into a `FileOverview`.
    ///
    /// - Parameters:
    ///   - source: The Swift source code string.
    ///   - file: The file path to associate with declarations (for display purposes).
    /// - Returns: A `FileOverview` with all extracted declarations.
    public func parseSource(_ source: String, file: String = "<memory>") -> FileOverview {
        let tree = SyntaxTree(viewMode: .sourceAccurate, sourceBuffer: source)
        tree.collectChildren()

        // NOTE: Source is parsed twice — once by SyntaxSparrow above and once here for
        // SourceLocationConverter. SyntaxTree does not expose its internal SourceFileSyntax,
        // so we cannot reuse it.
        let converter = SourceLocationConverter(fileName: file, tree: Parser.parse(source: source))

        let declarations = extractChildren(from: tree, file: file, source: source, converter: converter)
        return FileOverview(file: file, declarations: declarations)
    }
}

private extension FileParser {

    // MARK: - Structure Conversion

    func convertStructure(
        _ structure: Structure,
        file: String,
        source: String,
        converter: SourceLocationConverter
    ) -> Declaration {
        structure.collectChildren(viewMode: .sourceAccurate)

        let children = extractChildren(from: structure, file: file, source: source, converter: converter)

        return Declaration(
            name: structure.name,
            kind: .struct,
            line: lineNumber(for: structure.node, converter: converter),
            attributes: structure.attributes.map { "@\($0.name)" },
            conformances: structure.inheritance,
            children: children
        )
    }

    // MARK: - Enumeration Conversion

    func convertEnumeration(
        _ enumeration: Enumeration,
        file: String,
        source: String,
        converter: SourceLocationConverter
    ) -> Declaration {
        enumeration.collectChildren(viewMode: .sourceAccurate)

        var children: [Declaration] = []

        // Enum cases
        for enumCase in enumeration.cases {
            let associatedValueStrings = enumCase.associatedValues.map { param -> String in
                let label = param.name.flatMap { $0 == "_" ? nil : $0 }
                let rawType = param.rawType ?? "Unknown"
                if let label {
                    return "\(label): \(rawType)"
                }
                return rawType
            }

            // Build the full serialized declaration for pattern matching
            let caseName = enumCase.name
            var fullDeclaration = caseName
            if associatedValueStrings.isNotEmpty {
                fullDeclaration += "(\(associatedValueStrings.joined(separator: ", ")))"
            }

            children.append(Declaration(
                name: caseName,
                kind: .case,
                line: lineNumber(for: enumCase.node, converter: converter),
                attributes: enumCase.attributes.map { "@\($0.name)" },
                conformances: [],
                children: [],
                associatedValues: associatedValueStrings,
                fullDeclaration: fullDeclaration
            ))
        }

        // Nested types from the enum
        children.append(contentsOf: extractChildren(from: enumeration, file: file, source: source, converter: converter))

        children.sort { $0.line < $1.line }

        return Declaration(
            name: enumeration.name,
            kind: .enum,
            line: lineNumber(for: enumeration.node, converter: converter),
            attributes: enumeration.attributes.map { "@\($0.name)" },
            conformances: enumeration.inheritance,
            children: children
        )
    }

    // MARK: - Class Conversion

    func convertClass(
        _ classDecl: Class,
        file: String,
        source: String,
        converter: SourceLocationConverter
    ) -> Declaration {
        classDecl.collectChildren(viewMode: .sourceAccurate)

        let children = extractChildren(from: classDecl, file: file, source: source, converter: converter)

        return Declaration(
            name: classDecl.name,
            kind: .class,
            line: lineNumber(for: classDecl.node, converter: converter),
            attributes: classDecl.attributes.map { "@\($0.name)" },
            conformances: classDecl.inheritance,
            children: children
        )
    }

    // MARK: - Protocol Conversion

    func convertProtocol(
        _ protocolDecl: ProtocolDecl,
        file: String,
        source: String,
        converter: SourceLocationConverter
    ) -> Declaration {
        protocolDecl.collectChildren(viewMode: .sourceAccurate)

        let children = extractChildren(from: protocolDecl, file: file, source: source, converter: converter)

        return Declaration(
            name: protocolDecl.name,
            kind: .protocol,
            line: lineNumber(for: protocolDecl.node, converter: converter),
            attributes: protocolDecl.attributes.map { "@\($0.name)" },
            conformances: protocolDecl.inheritance,
            children: children
        )
    }

    // MARK: - Typealias Conversion

    func convertTypealias(
        _ typealiasDecl: SyntaxSparrow.Typealias,
        converter: SourceLocationConverter
    ) -> Declaration {
        Declaration(
            name: typealiasDecl.name,
            kind: .typealias,
            line: lineNumber(for: typealiasDecl.node, converter: converter),
            attributes: typealiasDecl.attributes.map { "@\($0.name)" },
            conformances: []
        )
    }

    // MARK: - Extension Conversion

    func convertExtension(
        _ ext: SyntaxSparrow.Extension,
        file: String,
        source: String,
        converter: SourceLocationConverter
    ) -> Declaration {
        ext.collectChildren(viewMode: .sourceAccurate)

        let children = extractChildren(from: ext, file: file, source: source, converter: converter)

        return Declaration(
            name: ext.extendedType,
            kind: .extension,
            line: lineNumber(for: ext.node, converter: converter),
            attributes: ext.attributes.map { "@\($0.name)" },
            conformances: ext.inheritance,
            children: children
        )
    }

    // MARK: - Actor Conversion

    func convertActor(
        _ actorDecl: SyntaxSparrow.Actor,
        file: String,
        source: String,
        converter: SourceLocationConverter
    ) -> Declaration {
        actorDecl.collectChildren(viewMode: .sourceAccurate)

        let children = extractChildren(from: actorDecl, file: file, source: source, converter: converter)

        return Declaration(
            name: actorDecl.name,
            kind: .actor,
            line: lineNumber(for: actorDecl.node, converter: converter),
            attributes: actorDecl.attributes.map { "@\($0.name)" },
            conformances: actorDecl.inheritance,
            children: children
        )
    }

    // MARK: - Function Conversion

    func convertFunction(
        _ function: Function,
        converter: SourceLocationConverter
    ) -> Declaration {
        var parts = formatModifiers(function.modifiers)
        parts.append("func")
        parts.append(function.identifier)

        var decl = parts.joined(separator: " ")

        // Parameters
        let paramStrings = function.signature.input.map { $0.description }
        decl += "(\(paramStrings.joined(separator: ", ")))"

        // Effect specifiers
        if let asyncSpec = function.signature.effectSpecifiers?.asyncSpecifier {
            decl += " \(asyncSpec)"
        }
        if let throwsSpec = function.signature.effectSpecifiers?.throwsSpecifier {
            if let throwsId = function.signature.effectSpecifiers?.throwsIdentifier {
                decl += " \(throwsSpec)(\(throwsId))"
            } else {
                decl += " \(throwsSpec)"
            }
        }

        // Return type
        if let rawOutput = function.signature.rawOutputType {
            let trimmed = rawOutput.trimmingCharacters(in: .whitespaces)
            if trimmed.isNotEmpty {
                decl += " -> \(trimmed)"
            }
        }

        return Declaration(
            name: function.identifier,
            kind: .function,
            line: lineNumber(for: function.node, converter: converter),
            attributes: function.attributes.map { "@\($0.name)" },
            conformances: [],
            fullDeclaration: decl
        )
    }

    // MARK: - Variable Conversion

    func convertVariable(
        _ variable: Variable,
        converter: SourceLocationConverter
    ) -> Declaration {
        var parts = formatModifiers(variable.modifiers)
        parts.append(variable.keyword)
        parts.append(variable.name)

        var decl = parts.joined(separator: " ")

        // Type annotation
        let typeDesc = variable.type.description
        if typeDesc.isNotEmpty {
            if let someOrAny = variable.someOrAnyKeyword {
                decl += ": \(someOrAny) \(typeDesc)"
            } else {
                decl += ": \(typeDesc)"
            }
        }

        return Declaration(
            name: variable.name,
            kind: .variable,
            line: lineNumber(for: variable.node, converter: converter),
            attributes: variable.attributes.map { "@\($0.name)" },
            conformances: [],
            fullDeclaration: decl
        )
    }

    // MARK: - Initializer Conversion

    func convertInitializer(
        _ initializer: Initializer,
        converter: SourceLocationConverter
    ) -> Declaration {
        var parts = formatModifiers(initializer.modifiers)
        parts.append(initializer.isOptional ? "init?" : "init")

        var decl = parts.joined(separator: " ")

        // Parameters
        let paramStrings = initializer.parameters.map { $0.description }
        decl += "(\(paramStrings.joined(separator: ", ")))"

        // Effect specifiers
        if let asyncSpec = initializer.effectSpecifiers?.asyncSpecifier {
            decl += " \(asyncSpec)"
        }
        if let throwsSpec = initializer.effectSpecifiers?.throwsSpecifier {
            if let throwsId = initializer.effectSpecifiers?.throwsIdentifier {
                decl += " \(throwsSpec)(\(throwsId))"
            } else {
                decl += " \(throwsSpec)"
            }
        }

        return Declaration(
            name: "init",
            kind: .initializer,
            line: lineNumber(for: initializer.node, converter: converter),
            attributes: initializer.attributes.map { "@\($0.name)" },
            conformances: [],
            fullDeclaration: decl
        )
    }

    // MARK: - Child Extraction

    func extractChildren(
        from collecting: some SyntaxChildCollecting,
        file: String,
        source: String,
        converter: SourceLocationConverter
    ) -> [Declaration] {
        var children: [Declaration] = []

        for structure in collecting.structures {
            children.append(convertStructure(structure, file: file, source: source, converter: converter))
        }

        for enumeration in collecting.enumerations {
            children.append(convertEnumeration(enumeration, file: file, source: source, converter: converter))
        }

        for classDecl in collecting.classes {
            children.append(convertClass(classDecl, file: file, source: source, converter: converter))
        }

        for protocolDecl in collecting.protocols {
            children.append(convertProtocol(protocolDecl, file: file, source: source, converter: converter))
        }

        for typealiasDecl in collecting.typealiases {
            children.append(convertTypealias(typealiasDecl, converter: converter))
        }

        for function in collecting.functions {
            children.append(convertFunction(function, converter: converter))
        }

        for variable in collecting.variables {
            children.append(convertVariable(variable, converter: converter))
        }

        for ext in collecting.extensions {
            children.append(convertExtension(ext, file: file, source: source, converter: converter))
        }

        for actorDecl in collecting.actors {
            children.append(convertActor(actorDecl, file: file, source: source, converter: converter))
        }

        for initializer in collecting.initializers {
            children.append(convertInitializer(initializer, converter: converter))
        }

        children.sort { $0.line < $1.line }
        return children
    }

    // MARK: - Modifier Formatting

    func formatModifiers(_ modifiers: [SyntaxSparrow.Modifier]) -> [String] {
        modifiers.map { modifier in
            if let detail = modifier.detail {
                "\(modifier.name)(\(detail))"
            } else {
                modifier.name
            }
        }
    }

    // MARK: - Line Number Resolution

    func lineNumber(for node: some SyntaxProtocol, converter: SourceLocationConverter) -> Int {
        let location = node.startLocation(converter: converter)
        return location.line
    }
}
