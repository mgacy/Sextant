//
//  AttributeArguments.swift
//  Sextant
//
//  Created by Mathew Gacy on 9/22/26.
//  Copyright © 2026 Mathew Gacy. All rights reserved.
//

import Testing

@Suite("Attribute arguments", .serialized)
struct AttributeArgumentsFixture {

    @Test("Fetches a user", .disabled("flaky on CI"))
    func fetchesUser() {}

    @Test
    func bareTest() {}

    @Test()
    func emptyParentheses() {}

    @MainActor @available(iOS 17, *)
    func mixed() {}

    @available(iOS, deprecated: 17) @available(macOS, deprecated: 14)
    func repeated() {}

    @Test(
        "Multi-line display name",
        arguments: [Result<Int, any Error>.success(1)]
    )
    func multiLine(value: Result<Int, any Error>) {}

    @available(iOS 16, *)
    #if DEBUG
    @MainActor
    #endif
    @objc(conditionalName)
    func conditional() {}
}

enum Event {
    @available(*, deprecated, message: "Use renamed")
    case legacy, older
}
