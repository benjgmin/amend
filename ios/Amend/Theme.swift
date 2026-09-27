import SwiftUI
import UIKit

/// The app's look, the same as amend.watch: calm neutrals that follow light and dark mode, with
/// amber = action, cyan = IFR, grey = FYI and green = nothing changed.
enum EFB {
    static let bg = Color(light: 0xF6F7F9, dark: 0x0D1015)
    static let panel = Color(light: 0xFFFFFF, dark: 0x151920)
    static let panelHi = Color(light: 0xEFF1F4, dark: 0x1C212A)
    static let line = Color(light: 0xE3E6EB, dark: 0x262C36)
    static let text = Color(light: 0x0F1216, dark: 0xECEEF1)
    static let dim = Color(light: 0x5B6573, dark: 0x9AA3AF)
    static let faint = Color(light: 0x848E9A, dark: 0x6E7885)
    static let amber = Color(light: 0xB25E00, dark: 0xF5B040)
    static let cyan = Color(light: 0x0969B8, dark: 0x5CC2FF)
    static let green = Color(light: 0x15803D, dark: 0x4ADE80)

    static func mono(_ size: CGFloat, _ weight: Font.Weight = .regular) -> Font {
        .system(size: size, weight: weight, design: .monospaced)
    }
}

extension Color {
    /// a color that switches with the system appearance
    init(light: UInt32, dark: UInt32) {
        self.init(UIColor { traits in
            UIColor(hex: traits.userInterfaceStyle == .dark ? dark : light)
        })
    }
}

private extension UIColor {
    convenience init(hex: UInt32) {
        self.init(red: CGFloat((hex >> 16) & 0xFF) / 255,
                  green: CGFloat((hex >> 8) & 0xFF) / 255,
                  blue: CGFloat(hex & 0xFF) / 255,
                  alpha: 1)
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

/// small rounded label with a colored dot ("ACT 2", "In effect")
struct Annunciator: View {
    let text: String
    let color: Color
    var dot = true

    var body: some View {
        HStack(spacing: 5) {
            if dot {
                Circle().fill(color).frame(width: 6, height: 6)
            }
            Text(text)
                .font(.system(size: 12, weight: .medium))
                .lineLimit(1)
        }
        .fixedSize()                     // labels never wrap onto two lines
        .foregroundStyle(color)
        .padding(.leading, dot ? 7 : 8)
        .padding(.trailing, 8)
        .padding(.vertical, 3)
        .background(color.opacity(0.13), in: Capsule())
    }
}

/// "ACT 2  IFR 4  FYI 3" or "No change"
struct CountAnnunciators: View {
    let counts: Counts?
    var showNoChange = true

    var body: some View {
        HStack(spacing: 4) {
            if let counts, counts.total > 0 {
                ForEach(Priority.allCases) { level in
                    let n = count(level, counts)
                    if n > 0 { Annunciator(text: "\(level.short) \(n)", color: level.color) }
                }
            } else if showNoChange {
                Annunciator(text: "No change", color: EFB.green)
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

/// section title, sentence case
struct EFBHeader: View {
    let text: String
    var color: Color = EFB.dim

    var body: some View {
        Text(text)
            .font(.system(size: 14, weight: .semibold))
            .foregroundStyle(color)
    }
}

struct PanelModifier: ViewModifier {
    func body(content: Content) -> some View {
        content
            .padding(14)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(EFB.panel, in: RoundedRectangle(cornerRadius: 14))
            .overlay(RoundedRectangle(cornerRadius: 14).stroke(EFB.line, lineWidth: 1))
    }
}

extension View {
    func efbPanel() -> some View { modifier(PanelModifier()) }

    /// plain list row with no system chrome
    func efbRow(top: CGFloat = 4, bottom: CGFloat = 4) -> some View {
        self.listRowBackground(Color.clear)
            .listRowSeparator(.hidden)
            .listRowInsets(EdgeInsets(top: top, leading: 16, bottom: bottom, trailing: 16))
    }
}
