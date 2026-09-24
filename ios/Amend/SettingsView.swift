import SwiftUI
import UIKit
import UserNotifications

struct SettingsView: View {
    @Environment(AirportStore.self) private var store
    @Environment(\.dismiss) private var dismiss

    @AppStorage(SettingsKey.notifyEnabled) private var notifyEnabled = false
    @AppStorage(SettingsKey.notifyMode) private var notifyMode: NotifyMode = .action
    @AppStorage(SettingsKey.historyRange) private var historyRange: HistoryRange = .all
    @AppStorage(SettingsKey.historyShowFYI) private var historyShowFYI = false

    @AppStorage(SettingsKey.onboarded) private var onboarded = true
    @State private var permissionDenied = false
    @State private var testSent = false

    private let repo = URL(string: "https://github.com/benjgmin/amend")!
    private let nasr = URL(string: "https://www.faa.gov/air_traffic/flight_info/aeronav/aero_data/NASR_Subscription/")!
    private let dtpp = URL(string: "https://www.faa.gov/air_traffic/flight_info/aeronav/digital_products/dtpp/")!

    var body: some View {
        NavigationStack {
            Form {
                guideSection
                homeSection
                notificationSection
                historySection
                dataSection
                aboutSection
            }
            .scrollContentBackground(.hidden)
            .background(EFB.bg)
            .navigationBarTitleDisplayMode(.inline)
            .toolbarBackground(EFB.bg, for: .navigationBar)
            .toolbar {
                ToolbarItem(placement: .principal) {
                    Text("SETTINGS").font(EFB.mono(15, .bold)).tracking(2).foregroundStyle(EFB.text)
                }
                ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } }
            }
            .alert("Notifications are off", isPresented: $permissionDenied) {
                Button("Open Settings") {
                    if let url = URL(string: UIApplication.openSettingsURLString) {
                        UIApplication.shared.open(url)
                    }
                }
                Button("Cancel", role: .cancel) {}
            } message: {
                Text("Allow notifications for Amend in iOS Settings to get cycle alerts.")
            }
        }
    }

    // MARK: sections

    private var guideSection: some View {
        Section {
            NavigationLink { GuideView(showsDone: false) } label: {
                Label("How Amend works", systemImage: "book")
            }
            .listRowBackground(EFB.panel)
            Button {
                dismiss()
                onboarded = false        // the home screen shows the welcome again
            } label: {
                Label("Show welcome again", systemImage: "sparkles")
            }
            .listRowBackground(EFB.panel)
        } header: {
            EFBHeader(text: "Guide")
        }
    }

    private var homeSection: some View {
        Section {
            Picker("Home airport", selection: Binding(
                get: { store.home ?? "" },
                set: { store.setHome($0.isEmpty ? nil : $0) })) {
                Text("None").tag("")
                ForEach(store.saved, id: \.self) { id in
                    Text(label(id)).tag(id)
                }
            }
            .listRowBackground(EFB.panel)
        } header: {
            EFBHeader(text: "Home")
        } footer: {
            Text("Your home field is pinned at the top. Add more airports with + on the main screen.")
                .font(.footnote).foregroundStyle(EFB.faint)
        }
    }

    private var notificationSection: some View {
        Section {
            Toggle("New cycle alerts", isOn: Binding(
                get: { notifyEnabled },
                set: { on in
                    if on { Task { await enableNotifications() } } else { notifyEnabled = false }
                }))
                .listRowBackground(EFB.panel)
            if notifyEnabled {
                Picker("Other airports", selection: $notifyMode) {
                    ForEach(NotifyMode.allCases) { Text($0.title).tag($0) }
                }
                .listRowBackground(EFB.panel)
                Button(testSent ? "Sent" : "Send test notification") {
                    Task {
                        await NotificationManager.check(force: true)
                        testSent = true
                    }
                }
                .disabled(testSent)
                .listRowBackground(EFB.panel)
            }
        } header: {
            EFBHeader(text: "Notifications")
        } footer: {
            Text("Your home airport always notifies on any change. Amend checks for new FAA data in the background (iOS decides exactly when, usually a few times a day) and notifies once per cycle.")
                .font(.footnote).foregroundStyle(EFB.faint)
        }
    }

    private var historySection: some View {
        Section {
            Picker("Default range", selection: $historyRange) {
                ForEach(HistoryRange.allCases) { Text($0.rawValue).tag($0) }
            }
            .listRowBackground(EFB.panel)
            Toggle("Show FYI changes", isOn: $historyShowFYI)
                .listRowBackground(EFB.panel)
        } header: {
            EFBHeader(text: "History")
        }
    }

    private var dataSection: some View {
        Section {
            if let meta = store.meta {
                row("Cycle", "\(Cycle.efb(meta.fromCycle)) → \(Cycle.efb(meta.toCycle))")
                row("Status", meta.upcoming ? "UPCOMING" : "CURRENT")
                row("Charts", meta.includesCharts ? "INCLUDED" : "NOT AVAILABLE")
                row("Updated", updated(meta.generated))
            }
            row("Airports in directory", "\(store.airports.count)")
            Button("Refresh now") { Task { await store.refresh() } }
                .listRowBackground(EFB.panel)
            Button("Clear cached airport list", role: .destructive) { store.clearDirectoryCache() }
                .listRowBackground(EFB.panel)
        } header: {
            EFBHeader(text: "Data")
        } footer: {
            Text("Sources: FAA 28-day NASR subscription and d-TPP terminal procedures. Remarks are translated to plain English with AI; the original FAA text is always shown.")
                .font(.footnote).foregroundStyle(EFB.faint)
        }
    }

    private var aboutSection: some View {
        Section {
            row("Version", appVersion)
            Link("Source code on GitHub", destination: repo).listRowBackground(EFB.panel)
            Link("FAA NASR subscription", destination: nasr).listRowBackground(EFB.panel)
            Link("FAA d-TPP", destination: dtpp).listRowBackground(EFB.panel)
        } header: {
            EFBHeader(text: "About")
        } footer: {
            Text("NOT FOR NAVIGATION. Amend is an awareness and study tool. Always use official FAA publications, NOTAMs and a proper preflight briefing.")
                .font(EFB.mono(10)).foregroundStyle(EFB.faint)
        }
    }

    // MARK: helpers

    private func row(_ title: String, _ value: String) -> some View {
        HStack {
            Text(title).foregroundStyle(EFB.text)
            Spacer()
            Text(value).font(EFB.mono(13)).foregroundStyle(EFB.dim)
        }
        .listRowBackground(EFB.panel)
    }

    private func label(_ id: String) -> String {
        guard let name = store.info(for: id)?.name else { return id }
        return "\(id) · \(name)"
    }

    private func updated(_ iso: String) -> String {
        guard let d = ISO8601DateFormatter().date(from: iso) else { return iso }
        return d.formatted(.relative(presentation: .named)).uppercased()
    }

    private var appVersion: String {
        let v = Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "0.1"
        let b = Bundle.main.infoDictionary?["CFBundleVersion"] as? String ?? "1"
        return "\(v) (\(b))"
    }

    private func enableNotifications() async {
        if await NotificationManager.requestPermission() {
            notifyEnabled = true
            NotificationManager.scheduleRefresh()
        } else {
            notifyEnabled = false
            permissionDenied = true
        }
    }
}
