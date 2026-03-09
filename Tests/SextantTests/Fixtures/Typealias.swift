//
//  Typealias.swift
//  Sextant
//
//  Created by Mathew Gacy on 3/8/26.
//  Copyright © 2026 Mathew Gacy. All rights reserved.
//

import Foundation

public typealias ItemListState = ItemListReducer.State
public typealias ItemListAction = ItemListReducer.Action
public typealias AppState = AppReducer.State
typealias CompletionHandler = (Result<Data, Error>) -> Void
