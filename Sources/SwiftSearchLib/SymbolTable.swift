//
//  SymbolTable.swift
//  Sextant
//
//  Created by Mathew Gacy on 3/8/26.
//  Copyright © 2026 Mathew Gacy. All rights reserved.
//

import Foundation

/// An in-memory index of symbols populated from parsed file overviews.
///
/// Supports lookup by name (exact match) with optional kind filter.
/// Returns `SymbolEntry` with file, line, kind, and attributes.
public struct SymbolTable: Sendable {

    /// All indexed symbols, keyed by name for fast lookup.
    private let entriesByName: [String: [SymbolEntry]]

    /// Creates a symbol table from an array of file overviews.
    ///
    /// - Parameter overviews: The parsed file overviews to index.
    public init(overviews: [FileOverview]) {
        var entries: [String: [SymbolEntry]] = [:]

        for overview in overviews {
            Self.indexDeclarations(
                overview.declarations,
                file: overview.file,
                into: &entries
            )
        }

        self.entriesByName = entries
    }

    // MARK: - Lookup

    /// Looks up symbols by exact name match.
    ///
    /// - Parameter name: The symbol name to search for.
    /// - Returns: All matching symbol entries, or an empty array if none found.
    public func lookup(name: String) -> [SymbolEntry] {
        entriesByName[name] ?? []
    }

    /// Looks up symbols by exact name match, filtered by kind.
    ///
    /// - Parameters:
    ///   - name: The symbol name to search for.
    ///   - kind: The kind filter to apply.
    /// - Returns: Matching symbol entries of the specified kind, or an empty array if none found.
    public func lookup(name: String, kind: SymbolKind) -> [SymbolEntry] {
        (entriesByName[name] ?? []).filter { $0.kind == kind }
    }

    /// Returns all indexed symbols.
    public var allSymbols: [SymbolEntry] {
        entriesByName.values.flatMap { $0 }
    }

    // MARK: - Private

    private static func indexDeclarations(
        _ declarations: [Declaration],
        file: String,
        parentName: String = "",
        into entries: inout [String: [SymbolEntry]]
    ) {
        for decl in declarations {
            let entry = SymbolEntry(
                name: decl.name,
                kind: decl.kind,
                file: file,
                line: decl.line,
                parentName: parentName,
                fullDeclaration: decl.fullDeclaration,
                attributes: decl.attributes,
                conformances: decl.conformances,
                associatedValues: decl.associatedValues
            )

            entries[decl.name, default: []].append(entry)

            // Recurse into children
            indexDeclarations(
                decl.children,
                file: file,
                parentName: parentName.isEmpty ? decl.name : "\(parentName).\(decl.name)",
                into: &entries
            )
        }
    }
}
