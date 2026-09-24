import BackgroundTasks
import Foundation
import UserNotifications

/// "New FAA cycle: VRB 2 ACT · DAB 1 IFR". Runs in a background app refresh task a few
/// times a day; iOS decides exactly when. Posts once per cycle.
@MainActor
enum NotificationManager {
    /// must match Info.plist > Permitted background task scheduler identifiers
    static let taskID = "com.benjgmin.amend.refresh"

    static func requestPermission() async -> Bool {
        (try? await UNUserNotificationCenter.current()
            .requestAuthorization(options: [.alert, .sound, .badge])) ?? false
    }

    static func scheduleRefresh() {
        let request = BGAppRefreshTaskRequest(identifier: taskID)
        request.earliestBeginDate = Date(timeIntervalSinceNow: 6 * 3600)
        try? BGTaskScheduler.shared.submit(request)
    }

    /// the user has seen this cycle in the app, so don't notify about it later
    static func markSeen(_ cycle: String) {
        UserDefaults.standard.set(cycle, forKey: SettingsKey.lastNotifiedCycle)
    }

    /// force = the "send test notification" button: ignores the setting and the once-per-cycle rule
    static func check(force: Bool = false) async {
        let d = UserDefaults.standard
        guard force || d.bool(forKey: SettingsKey.notifyEnabled) else { return }
        guard let meta = try? await API.meta(), let index = try? await API.latestIndex() else { return }
        if !force && d.string(forKey: SettingsKey.lastNotifiedCycle) == meta.toCycle { return }

        let saved = d.stringArray(forKey: SettingsKey.saved) ?? []
        let mode = NotifyMode(rawValue: d.string(forKey: SettingsKey.notifyMode) ?? "") ?? .action
        let changed: [(String, Counts)] = saved.compactMap { id in
            index.airports[id].map { (id, $0) }
        }
        .sorted { ($0.1.action, $0.1.total) > ($1.1.action, $1.1.total) }
        // your home field is where you fly most, so any change there is worth a ping
        let home = d.string(forKey: SettingsKey.home)
        let hits = mode == .action ? changed.filter { $0.1.action > 0 || $0.0 == home } : changed

        if !force { markSeen(meta.toCycle) }
        guard !hits.isEmpty || force else { return }

        let content = UNMutableNotificationContent()
        content.title = meta.upcoming ? "New FAA cycle · EFF \(Cycle.efb(meta.toCycle))"
                                      : "FAA cycle now effective"
        if !hits.isEmpty {
            content.body = summary(hits)
        } else if !changed.isEmpty {
            // test button in "action only" mode: be clear there ARE changes, just no action items
            content.body = "No action items at your airports. Other changes: \(summary(changed))"
        } else {
            content.body = "No changes at your airports this cycle."
        }
        content.sound = .default
        try? await UNUserNotificationCenter.current().add(
            UNNotificationRequest(identifier: "cycle-\(meta.toCycle)", content: content, trigger: nil))
    }
}

extension NotificationManager {
    /// "VRB 2 ACT 1 IFR · BOS 1 FYI"
    static func summary(_ items: [(String, Counts)]) -> String {
        items.prefix(6).map { id, c in
            let parts = [(c.action, "ACT"), (c.ifr, "IFR"), (c.fyi, "FYI")]
                .filter { $0.0 > 0 }.map { "\($0.0) \($0.1)" }
            return "\(id) \(parts.joined(separator: " "))"
        }.joined(separator: " · ")
    }
}

/// shows banners even while the app is open (otherwise iOS hides them)
final class NotificationDelegate: NSObject, UNUserNotificationCenterDelegate {
    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter,
                                            willPresent notification: UNNotification) async
        -> UNNotificationPresentationOptions {
        [.banner, .sound]
    }
}
