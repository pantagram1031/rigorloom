import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;

import kr.dogfoot.hwp2hwpx.Hwp2Hwpx;
import kr.dogfoot.hwplib.object.HWPFile;
import kr.dogfoot.hwplib.reader.HWPReader;
import kr.dogfoot.hwpxlib.object.HWPXFile;
import kr.dogfoot.hwpxlib.writer.HWPXWriter;

/** Fixed, source-visible bridge for the quarantined Java diagnostic lane. */
public final class Hwp2HwpxBridge {
    private Hwp2HwpxBridge() {
    }

    public static void main(String[] args) throws Exception {
        if (args.length != 3 || !"convert".equals(args[0])) {
            System.exit(2);
        }

        Path input = Paths.get(args[1]).toAbsolutePath().normalize();
        Path output = Paths.get(args[2]).toAbsolutePath().normalize();
        if (input.equals(output) || !Files.isRegularFile(input)
                || Files.exists(output)) {
            System.exit(2);
        }

        HWPFile hwp = HWPReader.fromFile(input.toString());
        HWPXFile hwpx = Hwp2Hwpx.toHWPX(hwp);
        HWPXWriter.toFilepath(hwpx, output.toString());
        if (!Files.isRegularFile(output) || Files.size(output) <= 0L) {
            System.exit(1);
        }
    }
}
