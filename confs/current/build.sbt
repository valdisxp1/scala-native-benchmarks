name := "scala-native-benchmarks"
scalaVersion := "2.11.12"
enablePlugins(ScalaNativePlugin)
nativeLinkStubs := true
nativeGC := "immix"
nativeMode := "release"
nativeLTO := "thin"
