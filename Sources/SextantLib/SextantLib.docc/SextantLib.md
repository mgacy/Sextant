# ``SextantLib``

Structural Swift code search — parse, index, and query Swift declarations.

## Overview

SextantLib parses Swift source files into owned value types and provides structured queries that go beyond what grep or LSP can offer. All output is `Codable` and `Sendable`.

The library has three main layers:

1. **Scanning** — ``FileScanner`` walks a directory tree collecting `.swift` files.
2. **Parsing** — ``FileParser`` parses files into ``FileOverview`` trees via swift-syntax.
3. **Querying** — ``SymbolTable`` and ``StructuralQuery`` search the parsed results.

### Typical Workflow

```swift
let parser = FileParser()
let result = try await parser.parseFiles(in: "/path/to/project")

// Build an index and look up a symbol
let table = SymbolTable(overviews: result.overviews)
let matches = table.lookup(name: "AppReducer", kind: .struct)

// Or search for enum cases by pattern
let query = StructuralQuery()
let cases = try query.findEnumCases(matching: "Result<", in: result.overviews)
```

## Topics

### Scanning

- ``FileScanner``

### Parsing

- ``FileParser``
- ``ParseResult``
- ``ParseFailure``

### Models

- ``FileOverview``
- ``Declaration``
- ``SymbolKind``
- ``SymbolEntry``

### Querying

- ``SymbolTable``
- ``StructuralQuery``
- ``EnumCaseMatch``

### Encoding Utilities

- ``OmitEmpty``
- ``EmptyInitializable``
