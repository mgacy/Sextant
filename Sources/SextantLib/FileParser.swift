//
//  FileParser.swift
//  Sextant
//
//  Created by Mathew Gacy on 3/8/26.
//  Copyright © 2026 Mathew Gacy. All rights reserved.
//

// swiftlint:disable file_length
import Foundation
import SwiftParser
import SwiftSyntax

/// Parses Swift source files via swift-syntax into owned model types.
///
/// This is the **isolation boundary** for swift-syntax. No swift-syntax types escape this file.
/// All other code operates on `FileOverview`, `Declaration`, and `SymbolEntry`.
public struct FileParser: Sendable {

    public enum Error: Swift.Error, LocalizedError, Sendable {
        case fileUnreadable(path: String, underlying: any Swift.Error)

        public var errorDescription: String? {
            switch self {
            case let .fileUnreadable(path, underlying): "Cannot read file: \(path) (\(underlying.localizedDescription))"
            }
        }
    }

    public init() {}

    /// Parses multiple Swift files concurrently.
    ///
    /// Files are parsed in parallel using a `TaskGroup`. Results are sorted by file path
    /// for deterministic output. Parse failures for individual files are collected in the
    /// result rather than thrown.
    ///
    /// - Parameter paths: An array of absolute paths to `.swift` files.
    /// - Returns: A ``ParseResult`` containing successes and failures, both sorted by file path.
    public func parseFiles(atPaths paths: [String]) async -> ParseResult {
        let results = await withTaskGroup(
            of: (String, Swift.Result<FileOverview, Error>).self
        ) { group in
            for file in paths {
                group.addTask {
                    (file, self.parseFileResult(at: file))
                }
            }

            var collected: [(String, Swift.Result<FileOverview, Error>)] = []
            collected.reserveCapacity(paths.count)
            for await result in group {
                collected.append(result)
            }
            return collected
        }

        let sorted = results.sorted { $0.0 < $1.0 }

        var overviews: [FileOverview] = []
        overviews.reserveCapacity(paths.count)
        var failures: [ParseFailure] = []

        for (file, result) in sorted {
            switch result {
            case .success(let overview):
                overviews.append(overview)
            case .failure(let error):
                failures.append(ParseFailure(file: file, error: error))
            }
        }

        return ParseResult(overviews: overviews, failures: failures)
    }

    /// Scans a path for Swift files and parses them concurrently.
    ///
    /// If `path` points to a single file, parses just that file. If `path` points to a directory,
    /// recursively scans for `.swift` files (excluding build artifacts) and parses all of them.
    ///
    /// - Parameter path: A file or directory path to scan.
    /// - Returns: A ``ParseResult`` containing successes and failures.
    /// - Throws: `FileScanner.Error` if the path does not exist or the directory cannot be enumerated.
    public func parseFiles(in path: String) async throws(FileScanner.Error) -> ParseResult {
        let scanner = FileScanner()
        let files = try scanner.collectSwiftFiles(at: path)
        return await parseFiles(atPaths: files)
    }

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
    /// Source is parsed once via `Parser.parse(source:)`. The resulting `SourceFileSyntax` tree
    /// is used both for declaration extraction and `SourceLocationConverter` creation.
    ///
    /// Only explicit declaration syntax nodes are extracted. Conditional compilation blocks
    /// (`#if`/`#elseif`/`#else`) and freestanding macro expressions (e.g., `#Preview { ... }`)
    /// are skipped — declarations inside them are not surfaced. Attached macros
    /// (e.g., `@Reducer`, `@Observable`) are preserved as attributes on the declarations
    /// they annotate.
    ///
    /// - Parameters:
    ///   - source: The Swift source code string.
    ///   - file: The file path to associate with declarations (for display purposes).
    /// - Returns: A `FileOverview` with all extracted declarations.
    public func parseSource(_ source: String, file: String = "<memory>") -> FileOverview {
        // swiftlint:disable:previous cyclomatic_complexity
        let sourceFile = Parser.parse(source: source)
        let converter = SourceLocationConverter(fileName: file, tree: sourceFile)

        var declarations: [Declaration] = []
        for statement in sourceFile.statements {
            if let node = statement.item.as(StructDeclSyntax.self) {
                declarations.append(convertStructure(node, file: file, converter: converter))
            } else if let node = statement.item.as(EnumDeclSyntax.self) {
                declarations.append(convertEnumeration(node, file: file, converter: converter))
            } else if let node = statement.item.as(ClassDeclSyntax.self) {
                declarations.append(convertClass(node, file: file, converter: converter))
            } else if let node = statement.item.as(ProtocolDeclSyntax.self) {
                declarations.append(convertProtocol(node, file: file, converter: converter))
            } else if let node = statement.item.as(TypeAliasDeclSyntax.self) {
                declarations.append(convertTypealias(node, converter: converter))
            } else if let node = statement.item.as(FunctionDeclSyntax.self) {
                declarations.append(convertFunction(node, converter: converter))
            } else if let node = statement.item.as(VariableDeclSyntax.self) {
                declarations.append(convertVariable(node, converter: converter))
            } else if let node = statement.item.as(ExtensionDeclSyntax.self) {
                declarations.append(convertExtension(node, file: file, converter: converter))
            } else if let node = statement.item.as(ActorDeclSyntax.self) {
                declarations.append(convertActor(node, file: file, converter: converter))
            } else if let node = statement.item.as(InitializerDeclSyntax.self) {
                declarations.append(convertInitializer(node, converter: converter))
            }
        }
        declarations.sort { $0.line < $1.line }
        return FileOverview(file: file, declarations: declarations)
    }
}

// MARK: - Conversion

private extension FileParser {
    func convertStructure(
        _ node: StructDeclSyntax,
        file: String,
        converter: SourceLocationConverter
    ) -> Declaration {
        Declaration(
            name: node.name.text,
            kind: .struct,
            line: lineNumber(for: node, converter: converter),
            attributes: extractAttributes(from: node),
            conformances: extractInheritance(from: node.inheritanceClause),
            children: extractChildren(from: node.memberBlock, file: file, converter: converter)
        )
    }

    func convertEnumeration(
        _ node: EnumDeclSyntax,
        file: String,
        converter: SourceLocationConverter
    ) -> Declaration {
        var children: [Declaration] = []

        // Enum cases — EnumCaseDeclSyntax contains an elements list
        for member in node.memberBlock.members {
            guard let caseDecl = member.decl.as(EnumCaseDeclSyntax.self) else { continue }

            // Attributes live on EnumCaseDeclSyntax, propagate to each element
            let caseAttributes = caseDecl.attributes.compactMap { element in
                guard let attr = element.as(AttributeSyntax.self) else { return nil as String? }
                return "@\(attr.attributeName.trimmedDescription)"
            }

            for element in caseDecl.elements {
                let caseName = element.name.text

                let associatedValueStrings: [String] = element.parameterClause?.parameters.map { param in
                    let label: String? = if let text = param.firstName?.text, text != "_" { text } else { nil }
                    let type = param.type.trimmedDescription
                    if let label {
                        return "\(label): \(type)"
                    }
                    return type
                } ?? []

                var fullDeclaration = caseName
                if associatedValueStrings.isNotEmpty {
                    fullDeclaration += "(\(associatedValueStrings.joined(separator: ", ")))"
                }

                children.append(Declaration(
                    name: caseName,
                    kind: .case,
                    line: lineNumber(for: element, converter: converter),
                    attributes: caseAttributes,
                    conformances: [],
                    children: [],
                    associatedValues: associatedValueStrings,
                    fullDeclaration: fullDeclaration
                ))
            }
        }

        // Non-case members from the enum (methods, properties, nested types, etc.)
        children.append(contentsOf: extractChildren(from: node.memberBlock, file: file, converter: converter))
        children.sort { $0.line < $1.line }

        return Declaration(
            name: node.name.text,
            kind: .enum,
            line: lineNumber(for: node, converter: converter),
            attributes: extractAttributes(from: node),
            conformances: extractInheritance(from: node.inheritanceClause),
            children: children
        )
    }

    func convertClass(
        _ node: ClassDeclSyntax,
        file: String,
        converter: SourceLocationConverter
    ) -> Declaration {
        Declaration(
            name: node.name.text,
            kind: .class,
            line: lineNumber(for: node, converter: converter),
            attributes: extractAttributes(from: node),
            conformances: extractInheritance(from: node.inheritanceClause),
            children: extractChildren(from: node.memberBlock, file: file, converter: converter)
        )
    }

    func convertProtocol(
        _ node: ProtocolDeclSyntax,
        file: String,
        converter: SourceLocationConverter
    ) -> Declaration {
        Declaration(
            name: node.name.text,
            kind: .protocol,
            line: lineNumber(for: node, converter: converter),
            attributes: extractAttributes(from: node),
            conformances: extractInheritance(from: node.inheritanceClause),
            children: extractChildren(from: node.memberBlock, file: file, converter: converter)
        )
    }

    func convertTypealias(
        _ node: TypeAliasDeclSyntax,
        converter: SourceLocationConverter
    ) -> Declaration {
        Declaration(
            name: node.name.text,
            kind: .typealias,
            line: lineNumber(for: node, converter: converter),
            attributes: extractAttributes(from: node),
            conformances: []
        )
    }

    func convertExtension(
        _ node: ExtensionDeclSyntax,
        file: String,
        converter: SourceLocationConverter
    ) -> Declaration {
        Declaration(
            name: node.extendedType.trimmedDescription,
            kind: .extension,
            line: lineNumber(for: node, converter: converter),
            attributes: extractAttributes(from: node),
            conformances: extractInheritance(from: node.inheritanceClause),
            children: extractChildren(from: node.memberBlock, file: file, converter: converter)
        )
    }

    func convertActor(
        _ node: ActorDeclSyntax,
        file: String,
        converter: SourceLocationConverter
    ) -> Declaration {
        Declaration(
            name: node.name.text,
            kind: .actor,
            line: lineNumber(for: node, converter: converter),
            attributes: extractAttributes(from: node),
            conformances: extractInheritance(from: node.inheritanceClause),
            children: extractChildren(from: node.memberBlock, file: file, converter: converter)
        )
    }

    func convertFunction(
        _ node: FunctionDeclSyntax,
        converter: SourceLocationConverter
    ) -> Declaration {
        var parts = formatModifiers(node.modifiers)
        parts.append("func")
        parts.append(node.name.text)

        var decl = parts.joined(separator: " ")

        // Parameters — trimmedDescription strips trivia; remove trailing comma if present
        let paramStrings = node.signature.parameterClause.parameters.map { param in
            var desc = param.trimmedDescription
            if desc.hasSuffix(",") {
                desc = String(desc.dropLast()).trimmingCharacters(in: .whitespaces)
            }
            return desc
        }
        decl += "(\(paramStrings.joined(separator: ", ")))"

        // Effect specifiers
        if let asyncSpec = node.signature.effectSpecifiers?.asyncSpecifier {
            decl += " \(asyncSpec.trimmedDescription)"
        }
        if let throwsClause = node.signature.effectSpecifiers?.throwsClause {
            let throwsKeyword = throwsClause.throwsSpecifier.trimmedDescription
            if let errorType = throwsClause.type {
                decl += " \(throwsKeyword)(\(errorType.trimmedDescription))"
            } else {
                decl += " \(throwsKeyword)"
            }
        }

        // Return type
        if let returnType = node.signature.returnClause?.type.trimmedDescription {
            decl += " -> \(returnType)"
        }

        return Declaration(
            name: node.name.text,
            kind: .function,
            line: lineNumber(for: node, converter: converter),
            attributes: extractAttributes(from: node),
            conformances: [],
            fullDeclaration: decl
        )
    }

    func convertVariable(
        _ node: VariableDeclSyntax,
        converter: SourceLocationConverter
    ) -> Declaration {
        // Only the first binding is extracted. Multi-binding declarations
        // (e.g., `var x, y: Int`) are rare in Swift and not supported.
        guard let binding = node.bindings.first else {
            return Declaration(
                name: "<unknown>",
                kind: .variable,
                line: lineNumber(for: node, converter: converter),
                fullDeclaration: node.bindingSpecifier.text
            )
        }

        let name = binding.pattern.as(IdentifierPatternSyntax.self)?.identifier.text ?? binding.pattern.trimmedDescription

        var parts = formatModifiers(node.modifiers)
        parts.append(node.bindingSpecifier.text)
        parts.append(name)

        var decl = parts.joined(separator: " ")

        if let typeAnnotation = binding.typeAnnotation {
            decl += ": \(typeAnnotation.type.trimmedDescription)"
        }

        return Declaration(
            name: name,
            kind: .variable,
            line: lineNumber(for: node, converter: converter),
            attributes: extractAttributes(from: node),
            conformances: [],
            fullDeclaration: decl
        )
    }

    func convertInitializer(
        _ node: InitializerDeclSyntax,
        converter: SourceLocationConverter
    ) -> Declaration {
        var parts = formatModifiers(node.modifiers)
        parts.append(node.optionalMark != nil ? "init?" : "init")

        var decl = parts.joined(separator: " ")

        // Parameters
        let paramStrings = node.signature.parameterClause.parameters.map { param in
            var desc = param.trimmedDescription
            if desc.hasSuffix(",") {
                desc = String(desc.dropLast()).trimmingCharacters(in: .whitespaces)
            }
            return desc
        }
        decl += "(\(paramStrings.joined(separator: ", ")))"

        // Effect specifiers
        if let asyncSpec = node.signature.effectSpecifiers?.asyncSpecifier {
            decl += " \(asyncSpec.trimmedDescription)"
        }
        if let throwsClause = node.signature.effectSpecifiers?.throwsClause {
            let throwsKeyword = throwsClause.throwsSpecifier.trimmedDescription
            if let errorType = throwsClause.type {
                decl += " \(throwsKeyword)(\(errorType.trimmedDescription))"
            } else {
                decl += " \(throwsKeyword)"
            }
        }

        return Declaration(
            name: "init",
            kind: .initializer,
            line: lineNumber(for: node, converter: converter),
            attributes: extractAttributes(from: node),
            conformances: [],
            fullDeclaration: decl
        )
    }
}

// MARK: - Extraction

private extension FileParser {
    // swiftlint:disable:next cyclomatic_complexity
    func extractChildren(
        from memberBlock: MemberBlockSyntax,
        file: String,
        converter: SourceLocationConverter
    ) -> [Declaration] {
        var children: [Declaration] = []
        for member in memberBlock.members {
            let decl = member.decl
            if let node = decl.as(StructDeclSyntax.self) {
                children.append(convertStructure(node, file: file, converter: converter))
            } else if let node = decl.as(EnumDeclSyntax.self) {
                children.append(convertEnumeration(node, file: file, converter: converter))
            } else if let node = decl.as(ClassDeclSyntax.self) {
                children.append(convertClass(node, file: file, converter: converter))
            } else if let node = decl.as(ProtocolDeclSyntax.self) {
                children.append(convertProtocol(node, file: file, converter: converter))
            } else if let node = decl.as(TypeAliasDeclSyntax.self) {
                children.append(convertTypealias(node, converter: converter))
            } else if let node = decl.as(FunctionDeclSyntax.self) {
                children.append(convertFunction(node, converter: converter))
            } else if let node = decl.as(VariableDeclSyntax.self) {
                children.append(convertVariable(node, converter: converter))
            } else if let node = decl.as(ExtensionDeclSyntax.self) {
                children.append(convertExtension(node, file: file, converter: converter))
            } else if let node = decl.as(ActorDeclSyntax.self) {
                children.append(convertActor(node, file: file, converter: converter))
            } else if let node = decl.as(InitializerDeclSyntax.self) {
                children.append(convertInitializer(node, converter: converter))
            }
            // EnumCaseDeclSyntax is handled inside convertEnumeration only
            // IfConfigDeclSyntax (#if/#elseif/#else) is intentionally skipped
        }
        children.sort { $0.line < $1.line }
        return children
    }

    /// Extracts attribute names from a syntax node that conforms to `WithAttributesSyntax`.
    ///
    /// - Parameter node: A syntax node with attributes (e.g., `StructDeclSyntax`, `FunctionDeclSyntax`).
    /// - Returns: An array of attribute strings prefixed with `@` (e.g., `["@Reducer", "@MainActor"]`).
    func extractAttributes(from node: some WithAttributesSyntax) -> [String] {
        node.attributes.compactMap { element in
            guard let attr = element.as(AttributeSyntax.self) else { return nil }
            return "@\(attr.attributeName.trimmedDescription)"
        }
    }

    /// Extracts inherited type names from an inheritance clause.
    ///
    /// - Parameter clause: The optional inheritance clause (e.g., `: Codable, Sendable`).
    /// - Returns: An array of type name strings (e.g., `["Codable", "Sendable"]`).
    func extractInheritance(from clause: InheritanceClauseSyntax?) -> [String] {
        guard let clause else { return [] }
        return clause.inheritedTypes.map { $0.type.trimmedDescription }
    }
}

// MARK: - Other Helpers

private extension FileParser {
    /// Formats declaration modifiers into human-readable strings.
    ///
    /// - Parameter modifiers: The modifier list from a swift-syntax declaration node.
    /// - Returns: An array of modifier strings (e.g., `["private(set)", "static"]`).
    func formatModifiers(_ modifiers: DeclModifierListSyntax) -> [String] {
        modifiers.map { modifier in
            if let detail = modifier.detail {
                "\(modifier.name.text)(\(detail.detail.text))"
            } else {
                modifier.name.text
            }
        }
    }

    func parseFileResult(at path: String) -> Swift.Result<FileOverview, Error> {
        do {
            return .success(try parseFile(at: path))
        } catch {
            return .failure(error)
        }
    }

    func lineNumber(for node: some SyntaxProtocol, converter: SourceLocationConverter) -> Int {
        node.startLocation(converter: converter).line
    }
}
