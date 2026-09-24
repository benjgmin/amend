//
//  AmendApp.swift
//  Cyclewatch
//
//  Created by Benjamin Eccles on 9/23/26.
//


import SwiftUI
import UserNotifications

@main
struct AmendApp: App {
    @State private var store = AirportStore()
    @Environment(\.scenePhase) private var scenePhase
    private let notificationDelegate = NotificationDelegate()

    init() {
        UNUserNotificationCenter.current().delegate = notificationDelegate
    }

    var body: some Scene {
        WindowGroup {
            AirportsView()
                .environment(store)
                .preferredColorScheme(.dark)
                .tint(EFB.cyan)
        }
        .onChange(of: scenePhase) { _, phase in
            if phase == .background { NotificationManager.scheduleRefresh() }
        }
        .backgroundTask(.appRefresh(NotificationManager.taskID)) {
            await NotificationManager.scheduleRefresh()
            await NotificationManager.check()
        }
    }
}