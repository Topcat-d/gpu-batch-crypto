# SPDX-License-Identifier: Apache-2.0.
# This directory can be copied outside the checkout. Only the installed SDK
# is consumed; no CUDA language, Python, OpenSSL or source-tree include path.
cmake_minimum_required(VERSION 3.24)
project(batchcrypto_consumer LANGUAGES C)
find_package(batchcrypto 0.3 CONFIG REQUIRED)
add_executable(batchcrypto_consumer main.c)
target_link_libraries(batchcrypto_consumer PRIVATE batchcrypto::batchcrypto)
if(WIN32)
  add_custom_command(TARGET batchcrypto_consumer POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
      $<TARGET_FILE:batchcrypto::batchcrypto> $<TARGET_FILE_DIR:batchcrypto_consumer>)
endif()
include(CTest)
set(BC_CONSUMER_DEVICE "0" CACHE STRING "CUDA device ordinal for the consumer check")
add_test(NAME installed_consumer COMMAND batchcrypto_consumer ${BC_CONSUMER_DEVICE})
