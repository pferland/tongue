__author__ = 'sysferland'
from BeautifulSoup import BeautifulSoup
from difflib import SequenceMatcher as SM
from ffvideo import VideoStream
from ffvideo import DecoderError
from ffvideo import NoMoreData
import urllib2, ordereddict, os, sys, cymysql, time, re, hashlib, socket, subprocess, signal


def select_season_id(season, conn):
    cur = conn.cursor()
    cur.execute("SELECT `id` FROM `tongue`.`seasons` WHERE `season_name` = %s", season)
    row = cur.fetchone()
    if row:
        return row[0]
    else:
        return 0


def check_feeds(ffserver_IP, ffserver_port, sql_host, sql_u, sql_p):
    sconn = cymysql.connect(host=sql_host, user=sql_u, passwd=sql_p, db="tongue")
    cur = sconn.cursor()
    while 1:
        sconn.commit()
        time.sleep(0.5)
        try:
            html = urllib2.urlopen("http://"+ffserver_IP+":"+ffserver_port+"/stat.html")
            html.getcode()
        except urllib2.URLError:
            print "ffserver is offline."
            continue
        soup = BeautifulSoup(html.read())
        i = 0
        ii_f = 0
        jump = 0
        stats = {"stats": {}}
        all = soup.findAll("table")
        len_supply = len(all)
        for supply in all:
            i += 1
            if i == 1:
                ii = -1
                # Streams
                stats['stats'].update({"Streams": {}})
                for row in supply.findAll("tr"):
                    iii = 0
                    ii += 1
                    if ii == 0:
                        continue
                    for item in row.findAll(text=True):
                        if str(item) == " ":
                            continue
                        if jump > 0:
                            jump -= 1
                            continue
                        comp = SM(None, str(item), "index.html").ratio()
                        comp2 = SM(None, str(item), "stat.html").ratio()
                        if comp == 1.0 or comp2 == 1.0:
                            jump = 7
                            continue
                        if ii not in stats['stats']['Streams']:
                            stats['stats']['Streams'].update({ii: {}})

                        stats['stats']['Streams'][ii].update({iii: item})
                        iii += 1
            else:
                if i != len_supply:
                    # Feeds
                    ii_ = -1
                    if "Feeds" not in stats['stats']:
                        stats['stats'].update({"Feeds": {}})

                    stats['stats']['Feeds'].update({ii_f: {}})
                    for row in supply.findAll("tr"):
                        iii = 0
                        ii_ += 1
                        if ii_ == 0:
                            continue
                        for item in row.findAll(text=True):
                            if str(item) == " ":
                                continue
                            if jump > 0:
                                jump -= 1
                                continue
                            comp = SM(None, str(item), "Stream").ratio()
                            if comp == 1.0:
                                jump = 4
                                continue
                            if ii_ not in stats['stats']['Feeds'][ii_f]:
                                stats['stats']['Feeds'][ii_f].update({ii_: {}})

                            stats['stats']['Feeds'][ii_f][ii_].update({iii: item})
                            iii += 1
                    ii_f += 1
                else:
                    ii = -1
                    # Connections
                    stats['stats'].update({"Connections": {}})
                    for row in supply.findAll("tr"):
                        iii = 0
                        ii += 1
                        if ii == 0:
                            continue
                        for item in row.findAll(text=True):
                            if str(item) == " ":
                                continue
                            if jump > 0:
                                #jump -= 1
                                continue
                            comp = SM(None, str(item), "index.html").ratio()
                            comp2 = SM(None, str(item), "stat.html").ratio()
                            if comp == 1.0 or comp2 == 1.0:
                                continue
                            if ii not in stats['stats']['Connections']:
                                stats['stats']['Connections'].update({ii: {}})

                            stats['stats']['Connections'][ii].update({iii: item})
                            iii += 1

        temp = {}
        i = 0
        #print stats['stats']['Connections']
        for key, conn in stats['stats']['Connections'].items():
            if len(conn) < 8:
                del stats['stats']['Connections'][key]
                continue;
            temp.update({i: {}})
            temp[i].update(conn)
            i += 1
        del stats['stats']['Connections']
        stats['stats']['Connections'] = {}
        stats['stats']['Connections'].update(temp)

        used_streams = {}
        i = 0
        for conn in stats['stats']['Connections'].values():
            re1='.*?'	# Non-greedy match on filler
            re2='(\\(.*\\))'	# Round Braces 1
            rg = re.compile(re1+re2,re.IGNORECASE|re.DOTALL)
            m = rg.search(conn[1])
            if m:
                continue

            used_streams.update({i: {'feed':conn[1], 'dest':conn[2], 'http_stat': conn[4], 'sent': conn[7]}})
            i += 1
        used_streams = ordereddict.OrderedDict(sorted(used_streams.items(), key=lambda t: t[1]))
        for key, stream in stats['stats']['Streams'].items():
            #print "--------------"
            flag = 0
            for key, used in used_streams.items():
                if SM(None, stream[0], used['feed']).ratio() == 1.0:
                    #print "Feed " + str(stream[9]).strip() + " in use, Insert/Update its Data"
                    flag = 1
                    try:
                        cur.execute("INSERT INTO `tongue`.`feeds` (`feed`, `feed_server`, `in_use`, `dest`, `http_stat`, `sent`) VALUES (%s, %s, 1, %s, %s, %s)", (str(stream[9]).strip(), ffserver_IP+":"+ffserver_port, str(used['dest']), str(used['http_stat']).strip(), str(used['sent']).strip()))
                        sys.stdout.write("(+)")
                        sys.stdout.flush()
                    except cymysql.MySQLError:
                        cur.execute("UPDATE `tongue`.`feeds` SET `in_use` = 1, `dest` = %s, `http_stat` = %s, `sent` = %s WHERE `feed` = %s", (str(used['dest']), str(used['http_stat']).strip(), str(used['sent']).strip(), str(stream[9]).strip() ))
                        sys.stdout.write("[+]")
                        sys.stdout.flush()
                    sconn.commit()
                    del used_streams[key]

                    break
            if flag == 0:
                #print "Insert/Update Unused Feed: "+str(stream[9]).strip()
                try:
                    cur.execute("INSERT INTO `tongue`.`feeds` (`feed`, `feed_server`, `in_use`, `dest`, `http_stat`, `sent`) VALUES (%s, %s, 0, '', '', '')", (str(stream[9]).strip(), ffserver_IP+":"+ffserver_port ))
                    sys.stdout.write("+")
                    sys.stdout.flush()
                except cymysql.MySQLError:
                    cur.execute("UPDATE `tongue`.`feeds` SET `feed` = %s, `in_use` = 0, `dest` = '', `http_stat` = '', `sent` = '' where `feed` = %s", (str(stream[9]).strip() , str(stream[9]).strip()))
                    sys.stdout.write("-")
                    sys.stdout.flush()
                sconn.commit()
                continue


def select_show_id(show, conn):
    cur = conn.cursor()
    cur.execute("SELECT `id` FROM `tongue`.`shows` WHERE `show_name` = %s", show)
    row = cur.fetchone()
    if row:
        return row[0]
    else:
        return 0


def insert_show(show, conn):
    cur = conn.cursor()
    cur.execute("INSERT INTO `tongue`.`shows` (`id`, `show_name`) VALUES ('', %s)", show)
    conn.commit()
    return cur.lastrowid


def insert_season(season, show_id, conn):
    conn.commit()
    cur = conn.cursor()
    cur.execute("INSERT INTO `tongue`.`seasons` (`id`, `season_name`, `show_id`) VALUES ('', %s, %s)", (str(season), str(show_id)))
    conn.commit()
    return cur.lastrowid


def prep_sql_movies(Movies_mnt, conn):
    cur = conn.cursor()
    #print [name for name in os.listdir(Movies_mnt) if os.path.isdir(Movies_mnt)]
    mnt_path = Movies_mnt.split('/')
    mnt_num = (len(mnt_path) - 1)
    while 1:
        dvd_flag = 0
        grouped = 0
        group = 1
        prev_folder = ""
        for root, dirs, files in os.walk(Movies_mnt):
            path = root.split('/')
            #print path
            root_num = (len(path) - 1)
            sub = os.path.basename(root)
            if prev_folder != sub:
                grouped = 0
            for file in files:
                filepath = root+"/"+file
                #print filepath
                path_hash = hashlib.sha256(filepath).hexdigest()
                file_parts = file.split(".")
                ext = file_parts[-1].lower()
                if ext == "nfo" or ext == "jpg" or ext == "jpeg" or ext == "srt" or ext == "ifo" or ext == "bup" or ext == "nzb" or ext == "idx" or ext == "sfv" or ext == "txt" or ext == "db" or ext == "DS_Store":
                    continue
                cur.execute("SELECT `id` FROM `tongue`.`movie_files` WHERE `path_hash` = %s LIMIT 1", str(path_hash))
                row = cur.fetchone()
                #print filepath
                #print row
                if not row:
                    del file_parts[-1]
                    file_name_no_ext = "-".join(file_parts)
                else:
                    continue
                #print len(path)*'---'
                if mnt_num == root_num-1:
                    #print "In root: " + root
                    ii = 0
                else:
                    #print "Sub of root: " + sub + " : " + file
                    if sub.upper() == "VIDEO_TS":
                        #print "Is DVD Video: " + file
                        if dvd_flag == 1:
                            print "flag already set"
                            #continue
                        else:
                            dvd_flag = 1
                        file = sub
                    else:
                        dvd_flag = 0
                    lower_file = file.lower()

                    if "cd1" in lower_file or "cd2" in lower_file:
                        #print lower_file
                        if prev_folder != sub:
                            prev_folder = sub
                            grouped = 1
                            group += 1
                            #print
                    else:
                        grouped = 0
                if not dvd_flag:
                    try:
                        vs = VideoStream(filepath)
                    except DecoderError:
                        #pass
                        codec = "unknown"
                        length = 0
                        dimensions = "0x0"
                        print "Decoder Error :("
                    except NoMoreData:
                        codec = "unknown"
                        length = 0
                        dimensions = "0x0"
                        print "File corrupt??"
                    else:
                        frame = vs.get_frame_at_sec(200)
                        codec = vs.codec_name
                        hours = vs.duration/3600
                        minuets = (vs.duration/60) - (int(hours) * 60)
                        rg = re.compile('.*?\\d+.*?(\\d+)',re.IGNORECASE|re.DOTALL)
                        m = rg.search(str(minuets))
                        seconds = int(float("0."+ m.group(1)) * 60)

                        # print vs.duration, minuets, hours
                        length = "%dh:%02d:%02d" % (hours, minuets, seconds)
                        dimensions = "%dx%d" % (vs.frame_width, vs.frame_height)
                else:
                    codec = "RAWDVD"
                    length = 0
                    dimensions = "0x0"

                fullpath = filepath.replace("'", "\\'").replace(" ", "\\ ").replace("-", "\-").replace("&", "\&").replace(")", "\)").replace("(", "\(")
                file_ = file.replace("'", "\\'").replace(" ", "\\ ").replace("-", "\-").replace("&", "\&").replace(")", "\)").replace("(", "\(")
                #print "DVD Flag: " + str(dvd_flag)
                if dvd_flag == 1:
                    file_ = path[-2]
                if grouped == 0:
                    group_ins = 0
                else:
                    group_ins = group
                #print grouped, group_ins
                try:
                    cur.execute("INSERT INTO `tongue`.`movie_files` (`id`, `fullpath`, `filename`, `path_hash`, `grouped`, `group`, `dvd_raw`, `runtime`, `dimensions`, `codec`) VALUES (NULL, %s, %s, %s, %s, %s, %s, %s, %s, %s)", (fullpath.replace(os.path.dirname(root) ,""), file_, str(path_hash), grouped, group_ins, dvd_flag, length, dimensions, codec))
                except cymysql.MySQLError, e:
                    print e
                sys.stdout.write("`")
                sys.stdout.flush()
                conn.commit()
                #print len(path)*'---', file
        time.sleep(900)


def prep_sql_shows(Shows_mnt, conn):
    cur = conn.cursor()
    while 1:
        ii = 0
        for (dirpath, dirnames, filenames) in os.walk(os.path.normpath(Shows_mnt)):
            if filenames:
                for file in filenames:
                    if ".DS_Store" in file:
                        continue
                    file_parts = file.split(".")
                    ext = file_parts[-1].lower()
                    del file_parts[-1]
                    if ext == "nfo" or ext == "jpg" or ext == "jpeg" or ext == "srt" or ext == "ifo" or ext == "bup" or ext == "nzb" or ext == "idx" or ext == "sfv" or ext == "txt" or ext == "db" or ext == "part":
                        continue
                    paths = []
                    parse = ""
                    i = 0
                    while Shows_mnt != parse:
                        if i == 0:
                            paths.append(file)
                            parse = os.path.dirname(os.path.normpath(dirpath + "/" + file))
                        else:
                            if parse in paths:
                                parse = os.path.dirname(parse)
                        i += 1
                        paths.append(parse)

                    #print paths
                    path_string = ''.join(paths)
                    path_hash = hashlib.sha256(path_string).hexdigest()
                    #print path_hash
                    cur.execute("SELECT `id` FROM `tongue`.`video_files` WHERE `path_hash` = %s LIMIT 1", str(path_hash))
                    row = cur.fetchone()
                    #print row
                    if not row:
                        if ext != "rm":
                            filepath = dirpath+"/"+file
                            print filepath
                            file_parts = file.split(".")
                            ext = file_parts[-1].lower()
                            del file_parts[-1]
                            file_name_no_ext = "-".join(file_parts)
                            try:
                                vs = VideoStream(filepath)
                            except DecoderError:
                                #pass
                                codec = "unknown"
                                length = 0
                                dimensions = "0x0"
                                print "Decoder Error :("
                            except NoMoreData:
                                codec = "unknown"
                                length = 0
                                dimensions = "0x0"
                                print "File corrupt??"
                            else:
                                if vs.duration < 20:
                                    frame = vs.get_frame_at_sec(vs.duration/2)
                                else:
                                    frame = vs.get_frame_at_sec(20)
                                codec = vs.codec_name
                                hours = vs.duration/3600
                                minuets = (vs.duration/60) - (int(hours) * 60)
                                rg = re.compile('.*?\\d+.*?(\\d+)',re.IGNORECASE|re.DOTALL)
                                m = rg.search(str(minuets))
                                seconds = int(float("0."+ m.group(1)) * 60)

                                # print vs.duration, minuets, hours
                                length = "%dh:%02d:%02d" % (hours, minuets, seconds)
                                dimensions = "%dx%d" % (vs.frame_width, vs.frame_height)
                        if paths:
                            plen = len(paths)
                            if plen == 3:
                                video = str(paths[0])

                                show_folder = str(os.path.basename(paths[plen-2]))
                                show_id = select_show_id(show_folder.replace("'", "\\'").replace(" ", "\\ ").replace("-", "\-").replace("&", "\&").replace(")", "\)").replace("(", "\("), conn)
                                if show_id == 0:
                                    show_id = insert_show(show_folder.replace("'", "\\'").replace(" ", "\\ ").replace("-", "\-").replace("&", "\&").replace(")", "\)").replace("(", "\("), conn)

                                season_folder = str(os.path.basename(paths[plen-2]))
                                season_id = select_season_id(season_folder.replace("'", "\\'").replace(" ", "\\ ").replace("-", "\-").replace("&", "\&").replace(")", "\)").replace("(", "\("), conn)
                                if season_id == 0:
                                    season_id = insert_season(season_folder.replace("'", "\\'").replace(" ", "\\ ").replace("-", "\-").replace("&", "\&").replace(")", "\)").replace("(", "\("), show_id, conn)

                                try:
                                    cur.execute("INSERT INTO `tongue`.`video_files` (`id`, `video`, `season_id`, `show_id`, `path_hash`, `runtime`, `dimensions`) VALUES (NULL, %s, %s, %s, %s, %s, %s )", (video.replace("'", "\\'").replace(" ", "\\ ").replace("-", "\-").replace("&", "\&").replace(")", "\)").replace("(", "\("), season_id, show_id, str(path_hash), length, dimensions))
                                except cymysql.MySQLError, e:
                                    print e
                                else:
                                    #print paths[0]+"|=|"+os.path.basename(paths[plen-2])+"|=|"+os.path.basename(paths[plen-2])
                                    #print show_id, season_id
                                    if ii == 100:
                                        sys.stdout.write("\n")
                                        ii = 0
                                    ii += 1
                                    sys.stdout.write(".")
                                    sys.stdout.flush()
                            else:
                                video = str(paths[0])

                                show_folder = str(os.path.basename(paths[plen-2]))
                                show_id = select_show_id(show_folder.replace("'", "\\'").replace(" ", "\\ ").replace("-", "\-").replace("&", "\&").replace(")", "\)").replace("(", "\("), conn)
                                if show_id == 0:
                                    show_id = insert_show(show_folder.replace("'", "\\'").replace(" ", "\\ ").replace("-", "\-").replace("&", "\&").replace(")", "\)").replace("(", "\("), conn)

                                season_folder = str(paths[plen-3].strip(Shows_mnt))
                                season_id = select_season_id(season_folder.replace("'", "\\'").replace(" ", "\\ ").replace("-", "\-").replace("&", "\&").replace(")", "\)").replace("(", "\("), conn)
                                if season_id == 0:
                                    season_id = insert_season(season_folder.replace("'", "\\'").replace(" ", "\\ ").replace("-", "\-").replace("&", "\&").replace(")", "\)").replace("(", "\("), show_id, conn)
                                try:
                                    cur.execute("INSERT INTO `tongue`.`video_files` (`id`, `video`, `season_id`, `show_id`, `path_hash`) VALUES (NULL, %s, %s, %s, %s )", (video.replace("'", "\\'").replace(" ", "\\ ").replace("-", "\-").replace("&", "\&").replace(")", "\)").replace("(", "\("), season_id, show_id, str(path_hash)))
                                except cymysql.MySQLError, e:
                                    print e
                                sys.stdout.write(".")
                                sys.stdout.flush()
                            conn.commit()
        time.sleep(900)

def fetch_waiting(conn):
    conn.commit()
    cur = conn.cursor()
    cur.execute("SELECT `table` FROM `waiting` ORDER BY `id` LIMIT 1")
    table_ = cur.fetchone()
    if table_:
        if table_[0] == "video_files":
            cur.execute("SELECT `waiting`.`id`, `waiting`.`feed`, `waiting`.`feed_server`, `waiting`.`seek`, `shows`.`show_name`"+
            ", `seasons`.`season_name`, `video_files`.`video` FROM `tongue`.`waiting`, `tongue`.`video_files`, `tongue`.`seasons`, "+
            "`tongue`.`shows` WHERE `video_files`.`id` = `waiting`.`video_id` AND `seasons`.`id` = `video_files`.`season_id` AND "+
            "`shows`.`id` = `video_files`.`show_id` ORDER BY `waiting`.`id` ASC LIMIT 1")
        elif table_[0] == "movie_files":
            cur.execute("SELECT `waiting`.`id`, `waiting`.`video_id`, `waiting`.`feed`, `waiting`.`feed_server`, `waiting`.`seek`, `movie_files`.`fullpath`, `movie_files`.`group`, `movie_files`.`grouped`, `movie_files`.`dvd_raw` FROM `tongue`.`waiting`, `tongue`.`movie_files` WHERE `movie_files`.`id` = `waiting`.`video_id` ORDER BY `waiting`.`id` ASC LIMIT 1")
    row = cur.fetchone()
    if row:
        row = row + (table_[0],)
        return row
    else:
        return 0


def remove_waiting(id, conn):
    conn.commit()
    cur = conn.cursor()
    cur.execute("DELETE FROM `tongue`.`waiting` WHERE `id` = %s", int(id))
    conn.commit()


def get_unused_feeds(conn):
    conn.commit()
    cur = conn.cursor()
    cur.execute("SELECT * FROM `tongue`.`feeds` WHERE `in_use` != 1")
    row = cur.fetchall()
    if row:
        return row
    else:
        return 0


def clean_threads(unused_feeds, threads):
    rm = []
    procs = []
    for thread in threads:
        #continue
        for feed in unused_feeds:
            if threads[thread]['feed'] in feed:
                #print thread['proc'].pid
                first_letter = str(threads[thread]['feed'])[0:1]
                alteredFeed = "["+first_letter+"]"+str(threads[thread]['feed'][1:])
                #find all PIDs for the feed : ps ax|grep [f]eed%.ffm
                ps = subprocess.check_output("ps -eo pid,command|grep "+alteredFeed, shell=True).split("\n")
                #print ps
                for proc in ps:
                    proc = proc.lstrip().rstrip()
                    if proc == "":
                        continue
                    #print proc
                    #print proc.split(" ")[0]
                    procs.append(proc.split(" ")[0])
                    #print "----------------------"
                procs.reverse()
                for proc in procs:
                    #print "Killed: "+str(proc)
                    os.kill(int(proc), signal.SIGKILL)
                sys.stdout.write("<-"+str(thread)+">")
                sys.stdout.flush()
                rm.append(thread)
    return rm


def tongue_socket(HOST, PORT): # A socket process that just listens and responds with what was sent to it.
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM) # init socket class
    s.bind((HOST, PORT)) # Bind to IP and Port
    s.listen(1) # Tell it to listen on that IP and Port
    while 1:
        conn, addr = s.accept() # Accept connection
        print 'Connected by', addr
        data = conn.recv(1024) #Look for 1k of data
        if not data: continue # if data is empty ignore
        conn.send(data) # if data is there, send it back
    conn.close() # not sure ho you would get here seeing how there is no break out of the while loop


def play_file(feed, feed_server, seek, fullpath, bin_path):
    command = 'python StreamThread.py -feed '+str(feed)+' -ffserver '+str(feed_server)+' -seek '+str(seek)+' -source '+str(fullpath)+' -binpath '+str(bin_path)
    command = command.replace("&", "\&")
    print command
    subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return 0

