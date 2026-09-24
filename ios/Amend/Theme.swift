import SwiftUI

/// Cockpit / EFB look. Colors follow avionics convention:
/// amber = caution (action), cyan = advisory (IFR), green = normal (no changes).
enum EFB {
    static let bg = Color(red: 0.035, green: 0.047, blue: 0.063)
    static let panel = Color(red: 0.075, green: 0.094, blue: 0.122)
    static let panelHi = Color(red: 0.106, green: 0.129, blue: 0.165)
    static let line = Color.white.opacity(0.09)
    static let text = Color(white: 0.94)
    static let dim = Color(white: 0.56)
    static let faint = Color(white: 0.36)
    static let amber = Color(red: 1.0, green: 0.71, blue: 0.0)
    static let cyan = Color(red: 0.24, green: 0.84, blue: 1.0)
    static let green = Color(red: 0.30, green: 0.88, blue: 0.45)

    static func mono(_ size: CGFloat, _ weight: Font.Weight = .regular) -> Font {
        .system(size: size, weight: weight, design: .monospaced)
    }
}

extension Priority {
    var color: Color {
        switch self {
        case .action: EFB.amber
        case .ifr: EFB.cyan
        case .fyi: EFB.dim
        }
    }

    var short: String {
        switch self {
        case .action: "ACT"
        case .ifr: "IFR"
        case .fyi: "FYI"
        }
    }
}

/// small boxed label, like an annunciator light
struct Annunciator: View {
    let text: String
    let color: Color

    var body: some View {
        Text(text)
            .font(EFB.mono(11, .bold))
            .lineLimit(1)
            .fixedSize()                 // annunciators never wrap onto two lines
            .foregroundStyle(color)
            .padding(.horizontal, 6)
            .padding(.vertical, 3)
            .background(color.opacity(0.12), in: RoundedRectangle(cornerRadius: 3))
            .overlay(RoundedRectangle(cornerRadius: 3).stroke(color.opacity(0.55), lineWidth: 1))
    }
}

/// "ACT 2  IFR 4  FYI 3" or "NO CHG"
struct CountAnnunciators: View {
    let counts: Counts?
    var showNoChange = true

    var body: some View {
        HStack(spacing: 5) {
            if let counts, counts.total > 0 {
                ForEach(Priority.allCases) { level in
                    let n = count(level, counts)
                    if n > 0 { Annunciator(text: "\(level.short) \(n)", color: level.color) }
                }
            } else if showNoChange {
                Annunciator(text: "NO CHG", color: EFB.green)
            }
        }
    }

    private func count(_ level: Priority, _ c: Counts) -> Int {
        switch level {
        case .action: c.action
        case .ifr: c.ifr
        case .fyi: c.fyi
        }
    }
}

struct EFBHeader: View {
    let text: String
    var color: Color = EFB.dim

    var body: some View {
        Text(text.uppercased())
            .font(EFB.mono(11, .semibold))
            .tracking(1.5)
            .foregroundStyle(color)
    }
}

struct PanelModifier: ViewModifier {
    func body(content: Content) -> some View {
        content
            .padding(12)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(EFB.panel, in: RoundedRectangle(cornerRadius: 8))
            .overlay(RoundedRectangle(cornerRadius: 8).stroke(EFB.line, lineWidth: 1))
    }
}

extension View {
    func efbPanel() -> some View { modifier(PanelModifier()) }

    /// plain dark list row with no system chrome
    func efbRow(top: CGFloat = 4, bottom: CGFloat = 4) -> some View {
        self.listRowBackground(Color.clear)
            .listRowSeparator(.hidden)
            .listRowInsets(EdgeInsets(top: top, leading: 16, bottom: bottom, trailing: 16))
    }
}
