import SwiftUI

/// First-launch onboarding: what it is, how to read it, set up home + alerts.
/// Shown again from Settings > Show welcome again.
struct WelcomeView: View {
    @Environment(AirportStore.self) private var store
    @AppStorage(SettingsKey.onboarded) private var onboarded = false
    @AppStorage(SettingsKey.notifyEnabled) private var notifyEnabled = false

    @State private var page = 0
    @State private var showingAdd = false
    @State private var showingGuide = false

    private let pages = 3

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Spacer()
                if page < pages - 1 {
                    Button("Skip") { onboarded = true }
                        .font(.system(size: 15, weight: .medium))
                        .foregroundStyle(EFB.dim)
                }
            }
            .frame(height: 44)
            .padding(.horizontal)

            TabView(selection: $page) {
                intro.tag(0)
                reading.tag(1)
                setup.tag(2)
            }
            .tabViewStyle(.page(indexDisplayMode: .never))

            footer
        }
        .background(EFB.bg)
        .sheet(isPresented: $showingAdd) { AddAirportView() }
        .sheet(isPresented: $showingGuide) { NavigationStack { GuideView() } }
    }

    // MARK: pages

    private var intro: some View {
        pageLayout(icon: "airplane.departure", title: "Welcome to Amend", logo: true) {
            Text("Every 28 days the FAA publishes a new cycle of airport, airspace and chart data. Tower hours move, runways get renumbered, approaches get amended, and it's easy to miss.")
            Text("Amend compares each cycle to the last one and tells you what changed at your airports, in plain English, up to three weeks before it takes effect.")
        }
    }

    private var reading: some View {
        pageLayout(icon: "list.bullet.rectangle", title: "How to read it") {
            chip("ACT", EFB.amber, "Changes how you fly it: tower hours, frequencies, runways, navaids")
            chip("IFR", EFB.cyan, "Approaches, STARs, departures and IFR routes")
            chip("FYI", EFB.dim, "Worth knowing: phone numbers, fees, obstacles, reworded remarks")
            chip("No change", EFB.green, "Nothing changed there this cycle")
            Text("Remarks are the FAA's free-text airport notes. They're translated to plain English, and the original FAA text is always one tap away.")
            Button("Read the full guide") { showingGuide = true }
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(EFB.cyan)
        }
    }

    private var setup: some View {
        pageLayout(icon: "house", title: "Set up") {
            Text("Add your home field first. You'll be notified about any change there, and about action items at your other airports.")

            Button { showingAdd = true } label: {
                setupRow(done: store.home != nil,
                         title: store.home.map { "Home: \($0)" } ?? "Choose home airport",
                         icon: "house.fill")
            }
            .buttonStyle(.plain)

            Button {
                Task {
                    if await NotificationManager.requestPermission() {
                        notifyEnabled = true
                        NotificationManager.scheduleRefresh()
                    }
                }
            } label: {
                setupRow(done: notifyEnabled, title: notifyEnabled ? "Cycle alerts on" : "Turn on cycle alerts",
                         icon: "bell.fill")
            }
            .buttonStyle(.plain)

            Text("Not for navigation. Always use official FAA publications, NOTAMs and a proper preflight briefing.")
                .font(.footnote)
                .foregroundStyle(EFB.faint)
        }
    }

    // MARK: pieces

    private var footer: some View {
        VStack(spacing: 16) {
            HStack(spacing: 8) {
                ForEach(0..<pages, id: \.self) { i in
                    Capsule()
                        .fill(i == page ? EFB.cyan : EFB.faint)
                        .frame(width: i == page ? 22 : 8, height: 6)
                }
            }
            .animation(.snappy, value: page)

            Button {
                if page < pages - 1 {
                    withAnimation { page += 1 }
                } else {
                    onboarded = true
                }
            } label: {
                Text(page < pages - 1 ? "Next" : "Get started")
                    .font(.system(size: 16, weight: .semibold))
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 14)
                    .foregroundStyle(EFB.bg)
                    .background(EFB.text, in: RoundedRectangle(cornerRadius: 12))
            }
        }
        .padding()
    }

    private func pageLayout<Content: View>(icon: String, title: String, logo: Bool = false,
                                     @ViewBuilder _ content: () -> Content) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                Group {
                    if logo {
                        Image("Logo")
                            .resizable()
                            .frame(width: 52, height: 52)
                            .accessibilityHidden(true)
                    } else {
                        Image(systemName: icon)
                            .font(.system(size: 40, weight: .semibold))
                            .foregroundStyle(EFB.cyan)
                    }
                }
                .padding(.top, 24)
                Text(title)
                    .font(.system(size: 28, weight: .semibold))
                    .foregroundStyle(EFB.text)
                VStack(alignment: .leading, spacing: 14) { content() }
                    .font(.body)
                    .foregroundStyle(EFB.text.opacity(0.85))
                    .fixedSize(horizontal: false, vertical: true)
            }
            .padding(.horizontal, 24)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private func chip(_ label: String, _ color: Color, _ text: String) -> some View {
        HStack(alignment: .top, spacing: 12) {
            Annunciator(text: label, color: color).frame(width: 70, alignment: .leading)
            Text(text).font(.subheadline)
        }
    }

    private func setupRow(done: Bool, title: String, icon: String) -> some View {
        HStack(spacing: 12) {
            Image(systemName: done ? "checkmark.circle.fill" : icon)
                .foregroundStyle(done ? EFB.green : EFB.cyan)
                .frame(width: 24)
            Text(title)
                .font(.system(size: 15, weight: .semibold))
                .foregroundStyle(done ? EFB.green : EFB.text)
            Spacer()
            if !done { Image(systemName: "chevron.right").foregroundStyle(EFB.faint) }
        }
        .efbPanel()
    }
}
