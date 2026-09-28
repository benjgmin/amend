//
//  AmendApp.swift
//  Cyclewatch
//
//


import SwiftUI
import UserNotifications

@main
struct AmendApp: App {
    @State private var store = AirportStore()
    @Environment(\.scenePhase) private var scenePhase
    @AppStorage(SettingsKey.appearance) private var appearance: Appearance = .system
    private let notificationDelegate = NotificationDelegate()

    init() {
        UNUserNotificationCenter.current().delegate = notificationDelegate
    }

    var body: some Scene {
        WindowGroup {
            AirportsView()
                .environment(store)
                .preferredColorScheme(appearance.colorScheme)
                .tint(EFB.cyan)
        }
        .onChange(of: scenePhase) { _, phase in
            if phase == .background { NotificationManager.scheduleRefresh() }
            // back from the background after 0901Z: "Upcoming" becomes "Latest" without a refresh
            if phase == .active { CycleClock.shared.recheck(store.meta?.toCycle) }
        }
        .backgroundTask(.appRefresh(NotificationManager.taskID)) {
            await NotificationManager.scheduleRefresh()
            await NotificationManager.check()
        }
    }
}