// RCE test server for Defects4J. One JVM per bug.
// Reads commands on stdin, one per line, answers on stdout:
//   COMPILE <out dir> <classpath> <file>   -> OK | ERR
//   TEST <classpath> <Class[::method]>...  -> FAIL <id> lines, then DONE <n>
// Each TEST runs in a fresh class loader over the classpath, so recompiled
// classes are picked up and static state does not leak between candidates.
import java.io.*;
import java.net.*;
import java.util.*;
import javax.tools.*;

public class RceRunner {
    public static List<String> run(String[] tests) throws Exception {
        List<String> out = new ArrayList<>();
        for (String a : tests) {
            String[] p = a.split("::");
            Class<?> c = Class.forName(p[0], true, Thread.currentThread().getContextClassLoader());
            org.junit.runner.Request r = p.length > 1 ? org.junit.runner.Request.method(c, p[1]) : org.junit.runner.Request.aClass(c);
            org.junit.runner.Result res = new org.junit.runner.JUnitCore().run(r);
            for (org.junit.runner.notification.Failure f : res.getFailures()) {
                String d = f.getDescription().getMethodName();
                out.add(p[0] + "::" + (d == null ? "?" : d));
            }
        }
        return out;
    }

    public static void main(String[] args) throws Exception {
        String self = new File(RceRunner.class.getProtectionDomain().getCodeSource().getLocation().toURI()).getPath();
        JavaCompiler jc = ToolProvider.getSystemJavaCompiler();
        BufferedReader in = new BufferedReader(new InputStreamReader(System.in));
        PrintStream out = new PrintStream(new FileOutputStream(FileDescriptor.out), true);
        System.setOut(new PrintStream(OutputStream.nullOutputStream()));
        System.setErr(new PrintStream(OutputStream.nullOutputStream()));
        String line;
        while ((line = in.readLine()) != null) {
            String[] w = line.split(" ");
            if (w[0].equals("COMPILE")) {
                int rc = jc.run(null, OutputStream.nullOutputStream(), OutputStream.nullOutputStream(),
                    "-nowarn", "-encoding", "ISO-8859-1", "-source", "1.8", "-target", "1.8", "-d", w[1], "-cp", w[2], w[3]);
                out.println(rc == 0 ? "OK" : "ERR");
            } else if (w[0].equals("TEST")) {
                List<URL> urls = new ArrayList<>();
                urls.add(new File(self).toURI().toURL());
                for (String e : w[1].split(":")) urls.add(new File(e).toURI().toURL());
                URLClassLoader l = new URLClassLoader(urls.toArray(new URL[0]), ClassLoader.getPlatformClassLoader());
                Thread.currentThread().setContextClassLoader(l);
                try {
                    Class<?> rr = l.loadClass("RceRunner");
                    @SuppressWarnings("unchecked")
                    List<String> f = (List<String>) rr.getMethod("run", String[].class).invoke(null, (Object) Arrays.copyOfRange(w, 2, w.length));
                    for (String s : f) out.println("FAIL " + s);
                    out.println("DONE " + f.size());
                } catch (Throwable t) {
                    out.println("DONE -1");
                }
                l.close();
            }
        }
    }
}
