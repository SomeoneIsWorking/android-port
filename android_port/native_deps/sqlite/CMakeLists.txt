cmake_minimum_required(VERSION 3.24)
project(android_port_sqlite C)

if(NOT EXISTS "${SQLITE_SOURCE}/sqlite3.c")
  message(FATAL_ERROR "Pinned SQLite amalgamation is missing: ${SQLITE_SOURCE}")
endif()
add_library(sqlite3 STATIC "${SQLITE_SOURCE}/sqlite3.c")
target_compile_definitions(sqlite3 PRIVATE SQLITE_OMIT_LOAD_EXTENSION SQLITE_THREADSAFE=1)
install(TARGETS sqlite3 ARCHIVE DESTINATION lib)
install(FILES "${SQLITE_SOURCE}/sqlite3.h" "${SQLITE_SOURCE}/sqlite3ext.h" DESTINATION include)
file(CONFIGURE OUTPUT "${CMAKE_BINARY_DIR}/sqlite3.pc" CONTENT [[prefix=@CMAKE_INSTALL_PREFIX@
libdir=${prefix}/lib
includedir=${prefix}/include

Name: SQLite
Description: SQL database engine
Version: @SQLITE_VERSION@
Libs: -L${libdir} -lsqlite3
Libs.private: -lm
Cflags: -I${includedir}
]] @ONLY)
install(FILES "${CMAKE_BINARY_DIR}/sqlite3.pc" DESTINATION lib/pkgconfig)
