# Sextant

A structural Swift code search tool that gives coding agents (Claude Code, Cursor, Copilot, etc.) what grep and LSP can't: a machine-readable map of Swift code structure. It parses source files with [SyntaxSparrow](https://github.com/CheekyGhost-Labs/SyntaxSparrow) and [swift-syntax](https://github.com/swiftlang/swift-syntax) and outputs everything as JSON.

## Why

Coding agents navigate codebases with text search and file reads. This works fine for many languages, but Swift's structure fights it:

- **Nested types are invisible to grep.** A TCA feature nests `State`, `Action`, and `Destination` types inside a `@Reducer struct`. Grepping for `struct State` returns every feature's `State` with no way to tell which parent it belongs to. Sextant returns the full tree — parent, children, nesting depth — in one call.

- **Enum associated values carry the data model.** In Swift (especially TCA), enum cases like `case response(Result<Bool, any Error>)` define the data flow. Grep can find the case name, but can't search by associated value type. `swift-search enum-cases --pattern "Result<"` finds every case carrying a `Result`, with the parent enum and file location.

- **Attributes and conformances require parsing, not pattern matching.** Knowing that a type is `@Observable`, conforms to `Sendable`, or has a `@Dependency` property matters for understanding how code fits together. Sextant extracts these as structured fields.

- **JSON output is agent-native.** No regex over human-readable output. An agent gets structured data it can filter, count, and reason about directly. One `overview` call replaces reading an entire file and mentally parsing the AST.

The net effect: agents spend fewer tokens reading files, make fewer wrong assumptions about code structure, and can answer architectural questions ("which features handle this action?", "what types conform to this protocol?") without scanning every file.

## Installation

Requires macOS 14+ and Swift 6.2+.

```bash
git clone <repo-url>
cd Sextant
swift build
```

The executable is `swift-search`:

```bash
swift run swift-search --help
```

## Commands

### `overview` — File structure

Dump every declaration in a Swift file as a nested tree.

```bash
swift-search overview Sources/SwiftSearchLib/FileParser.swift
```

```json
[
  {
    "name": "FileParser",
    "kind": "struct",
    "line": 12,
    "conformances": ["Sendable"],
    "children": [
      {
        "name": "parseFile",
        "kind": "function",
        "line": 18,
        ...
      }
    ],
    ...
  }
]
```

### `lookup` — Symbol search

Find symbols by name across a directory tree, with an optional kind filter.

```bash
# Find all symbols named "State"
swift-search lookup State --path Sources/

# Find only structs named "State"
swift-search lookup State --kind struct --path Sources/
```

```json
[
  {
    "name": "State",
    "kind": "struct",
    "file": "Sources/SwiftSearchLib/Models/SymbolEntry.swift",
    "line": 20,
    "attributes": ["@ObservableState"],
    "conformances": ["Equatable"],
  }
]
```

**`--kind` values:** `struct`, `class`, `enum`, `protocol`, `typealias`, `function`, `variable`, `case`, `initializer`, `extension`, `actor`, `macro`

### `enum-cases` — Enum case search

Search enum cases with optional regex matching against the full serialized declaration (name + associated values).

```bash
# List all enum cases in a directory
swift-search enum-cases Sources/

# Find cases whose declaration matches a pattern
swift-search enum-cases Sources/ --pattern "Result<"
```

```json
[
  {
    "enumName": "Action",
    "caseName": "response",
    "associatedValues": ["Result<Bool, any Error>"],
    "fullDeclaration": "response(Result<Bool, any Error>)",
    "file": "Sources/App/Favoriting.swift",
    "line": 36
  }
]
```

The `--pattern` flag matches against `fullDeclaration`, so you can search by case name, associated value type, or any substring of the serialized form.

## Library

The `SwiftSearchLib` library can be used independently:

```swift
import SwiftSearchLib

// Parse a single file
let parser = FileParser()
let overview = try parser.parseFile(at: "Sources/App/Feature.swift")

// Build a symbol table from multiple files
let scanner = FileScanner()
let paths = try scanner.collectSwiftFiles(at: "Sources/")
let overviews = try paths.map { try parser.parseFile(at: $0) }
let table = SymbolTable(overviews: overviews)

// Exact-match lookup
let results = table.lookup(name: "State", kind: .struct)

// Regex search over enum cases
let query = StructuralQuery()
let cases = try query.findEnumCases(matching: "Result<", in: overviews)
```

### Key types

| Type | Role |
|---|---|
| `FileParser` | Parses Swift source into `FileOverview`. Isolation boundary for SyntaxSparrow. |
| `FileScanner` | Walks directories collecting `.swift` files (excludes `.build/`, `checkouts/`, etc.). |
| `SymbolTable` | In-memory index for fast name-based lookup with optional kind filter. |
| `StructuralQuery` | Regex-based enum case search and symbol-by-kind filtering. |
| `Declaration` | A single declaration node with name, kind, line, attributes, conformances, and children. |
| `FileOverview` | Top-level declarations for a file. |
| `SymbolEntry` | A flattened symbol record for index lookups. |

## Development

```bash
swift build              # Build
swift test               # Run all tests
swift run swift-search   # Run the CLI
mise run lint            # Lint with SwiftLint
```

## Dependencies

- [SyntaxSparrow](https://github.com/CheekyGhost-Labs/SyntaxSparrow) — High-level Swift syntax tree traversal
- [swift-syntax](https://github.com/swiftlang/swift-syntax) — Source location resolution
- [swift-argument-parser](https://github.com/apple/swift-argument-parser) — CLI framework
