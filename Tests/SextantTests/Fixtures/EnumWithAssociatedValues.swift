//
//  EnumWithAssociatedValues.swift
//  Sextant
//
//  Created by Mathew Gacy on 3/8/26.
//  Copyright © 2026 Mathew Gacy. All rights reserved.
//

import Foundation

public enum NetworkResult: Equatable, Sendable {
    case success(Data)
    case failure(AppError)
    case unauthorized
}

public enum DataEvent: Equatable, Sendable {
    case contentFetched(Result<PageContent, AppError>)
    case profileUpdated(Result<Profile, NetworkError>)
    case settingsLoaded(config: AppConfig, isFirstLaunch: Bool)
    case batchCompleted(results: [Result<Item, AppError>], timestamp: Date)
    case noPayload
}

@CasePathable
public enum NavigationAction: Equatable, Sendable {
    case push(route: Route, animated: Bool)
    case pop
    case presentSheet(SheetContent)
}
