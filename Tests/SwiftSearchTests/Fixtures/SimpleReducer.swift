//
//  SimpleReducer.swift
//  Sextant
//
//  Created by Mathew Gacy on 3/8/26.
//  Copyright © 2026 Mathew Gacy. All rights reserved.
//

import Foundation

public typealias ItemListAction = ItemListReducer.Action
public typealias ItemListState = ItemListReducer.State

@Reducer
public struct ItemListReducer: Reducer, Sendable {
    @Dependency(\.api) var api
    @Dependency(\.logger) var logger

    @ObservableState
    public struct State: Equatable {
        var items: [Item] = []
        var isLoading: Bool = false
        @Presents var destination: Destination.State?
    }

    @Reducer
    public enum Destination {
        case alert(AlertState<Never>)
        case detail(ItemDetailReducer)
    }

    @CasePathable
    public enum Action: BindableAction, Equatable, Sendable {
        case binding(BindingAction<State>)
        case destination(PresentationAction<Destination.Action>)
        case itemsFetched(Result<[Item], AppError>)
        case onAppear
        case delegate(Delegate)

        @CasePathable
        public enum Delegate: Equatable, Sendable {
            case itemSelected(Item)
        }
    }

    public init() {}

    public var body: some ReducerOf<Self> {
        BindingReducer()
        Reduce(core)
            .ifLet(\.$destination, action: \.destination)
    }
}

// MARK: - Private

private extension ItemListReducer {
    func core(state: inout State, action: Action) -> Effect<Action> {
        switch action {
        case .binding:
            return .none

        case .destination:
            return .none

        case .itemsFetched(.success(let items)):
            state.items = items
            state.isLoading = false
            return .none

        case .itemsFetched(.failure(let error)):
            state.isLoading = false
            state.destination = .alert(AlertState(title: TextState(error.localizedDescription)))
            return .none

        case .onAppear:
            state.isLoading = true
            return .run { send in
                do {
                    let items = try await api.fetchItems()
                    await send(.itemsFetched(.success(items)))
                } catch {
                    await send(.itemsFetched(.failure(AppError(error))))
                }
            }

        case .delegate:
            return .none
        }
    }
}
