plugins/snpxtr.so: plugins/snpxtr.c version.h version.c gemBS_plugins/utils.c gemBS_plugins/compress.c gemBS_plugins/compress.h gemBS_plugins/utils.h gemBS_plugins/uthash.h gemBS_plugins/snpxtr.h
	$(CC) $(PLUGIN_FLAGS) $(CFLAGS) $(ALL_CPPFLAGS) -I gemBS_plugins $(EXTRA_CPPFLAGS) $(LDFLAGS) -o $@ gemBS_plugins/utils.c gemBS_plugins/compress.c version.c $< $(LIBS)
