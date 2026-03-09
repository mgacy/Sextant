//
//  DeclarationsFixture.swift
//  Sextant
//
//  Created by Mathew Gacy on 3/8/26.
//  Copyright © 2026 Mathew Gacy. All rights reserved.
//

import Foundation

// MARK: - Functions

func simple() {}

static func validate(_ input: String) -> Bool {
    !input.isEmpty
}

public func fetchUser(id: UUID, includeProfile: Bool = true) async throws -> User {
    fatalError()
}

func process(items: String...) -> Int {
    items.count
}

mutating func reset() {
    count = 0
}

// MARK: - Variables

var isLoading: Bool = false
let name: String = "test"
static var shared: NetworkManager = NetworkManager()
public private(set) var count: Int = 0

// MARK: - Settings (Initializers)

struct Settings: Codable, Sendable {
    let id: UUID
    let name: String
    let retryCount: Int

    init(id: UUID, name: String) {
        self.id = id
        self.name = name
        self.retryCount = 3
    }

    init?(rawValue: String) {
        guard !rawValue.isEmpty else { return nil }
        self.id = UUID()
        self.name = rawValue
        self.retryCount = 0
    }

    public init() throws {
        self.id = UUID()
        self.name = ""
        self.retryCount = 0
    }
}

// MARK: - Extensions

extension String: CustomPrintable {
    func trimmed() -> String {
        trimmingCharacters(in: .whitespaces)
    }

    var isEmpty: Bool {
        count == 0 // swiftlint:disable:this empty_count
    }
}

private extension Array {
    func chunked(size: Int) -> [[Element]] {
        stride(from: 0, to: count, by: size).map {
            Array(self[$0..<Swift.min($0 + size, count)])
        }
    }
}

// MARK: - Actor

actor NetworkManager: Sendable {
    var requestCount: Int = 0

    func fetch(url: URL) async throws -> Data {
        requestCount += 1
        return Data()
    }
}

// MARK: - Enum (verify existing behavior)

enum Status {
    case active
    case inactive(reason: String)
}
