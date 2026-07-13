import datetime
import random
from app import create_app
from app.models import db, User, UserActivity, DiseaseNews

def seed_data():
    app = create_app()
    with app.app_context():
        print("Starting analytics seeding...")

        # 1. Fetch existing users
        users = User.query.all()
        if not users:
            print("No users found in database. Please run seed_admin.py or register users first.")
            return
        
        print(f"Found {len(users)} users. Generating historical activities...")

        # Clear existing simulated user activities to avoid duplicates (except admin logins, etc if wanted)
        # Let's delete all activities that are 'scan', 'symptom_check' or chatbot to start fresh
        deleted_count = UserActivity.query.filter(UserActivity.activity_type.in_(['scan', 'symptom_check', 'chatbot'])).delete(synchronize_session=False)
        print(f"Cleared {deleted_count} old activities.")

        # Data sets for descriptions
        scans = [
            ("scan", "Scan barcode obat Paracetamol 500mg - Verifikasi keaslian berhasil"),
            ("scan", "Scan barcode obat Amoxicillin 500mg - Verifikasi keaslian berhasil"),
            ("scan", "Scan barcode obat Ibuprofen 400mg - Dosis terverifikasi"),
            ("scan", "Scan barcode obat Cetirizine 10mg - Cek expired date: Aman"),
            ("scan", "Scan barcode obat Antasida Doen - Cek indikasi lambung"),
            ("scan", "Scan barcode obat Decolgen - Dosis influenza dewasa"),
            ("scan", "Scan barcode obat Ponstan 500mg - Verifikasi keaslian berhasil"),
            ("scan", "Scan barcode obat Diapet - Cek dosis diare"),
            ("scan", "Scan barcode obat Sanmol Syrup - Cek dosis anak"),
            ("scan", "Scan barcode obat Amoxsan - Verifikasi keaslian berhasil")
        ]

        symptoms = [
            ("symptom_check", "Cek gejala: Demam tinggi, nyeri sendi & bintik merah (Indikasi Demam Berdarah)"),
            ("symptom_check", "Cek gejala: Batuk kering, sesak napas & demam (Indikasi Pneumonia)"),
            ("symptom_check", "Cek gejala: Pilek, bersin-bersin, sakit tenggorokan (Indikasi Influenza)"),
            ("symptom_check", "Cek gejala: Diare cair mendadak, mual & lemas (Indikasi Gastroenteritis)"),
            ("symptom_check", "Cek gejala: Sakit kepala sebelah berdenyut (Indikasi Migrain)"),
            ("symptom_check", "Cek gejala: Nyeri ulu hati, mual & kembung (Indikasi Dispepsia/Maag)"),
            ("symptom_check", "Cek gejala: Gatal pada kulit kemerahan (Indikasi Alergi)"),
            ("symptom_check", "Cek gejala: Nyeri dada menusuk saat bernapas (Indikasi Pleuritis)")
        ]

        chats = [
            ("chatbot", "Konsultasi dosis obat Paracetamol untuk anak usia 5 tahun"),
            ("chatbot", "Tanya efek samping obat antibiotik Amoxicillin"),
            ("chatbot", "Konsultasi gejala pusing setelah minum obat flu Decolgen"),
            ("chatbot", "Tanya interaksi obat Ibuprofen dengan kopi hangat"),
            ("chatbot", "Konsultasi cara mengatasi mual muntah saat awal kehamilan"),
            ("chatbot", "Tanya obat maag yang aman diminum sebelum makan"),
            ("chatbot", "Tanya aturan minum Cetirizine apakah bikin ngantuk"),
            ("chatbot", "Konsultasi beda obat Sanmol dan Paracetamol biasa"),
            ("chatbot", "Konsultasi penanganan pertama demam pada bayi"),
            ("chatbot", "Tanya dosis suplemen Vitamin C harian untuk imun")
        ]

        logins = [
            ("login", "User masuk menggunakan email dan password"),
            ("login_google", "User masuk menggunakan Google Sign-In")
        ]

        now = datetime.datetime.utcnow()
        activity_records = []

        # Generate data for the last 30 days
        for day in range(30):
            target_date = now - datetime.timedelta(days=day)
            
            # Randomize count of activities for each day to make it look organic
            # Let's say, 10 to 30 activities per day in total across all users
            num_activities = random.randint(8, 25)
            
            for _ in range(num_activities):
                # Pick a random user
                user = random.choice(users)
                # Pick an activity category
                # We want a realistic distribution: chatbot is most active, then scans, then symptom checks, then logins
                choice = random.choices(
                    ['scan', 'symptom_check', 'chatbot', 'login'],
                    weights=[0.30, 0.25, 0.35, 0.10],
                    k=1
                )[0]

                if choice == 'scan':
                    act_type, desc = random.choice(scans)
                elif choice == 'symptom_check':
                    act_type, desc = random.choice(symptoms)
                elif choice == 'chatbot':
                    act_type, desc = random.choice(chats)
                else:
                    act_type, desc = random.choice(logins)

                # Generate a random time of day
                hour = random.randint(7, 23)
                minute = random.randint(0, 59)
                second = random.randint(0, 59)
                activity_time = target_date.replace(hour=hour, minute=minute, second=second)

                activity = UserActivity(
                    user_id=user.id,
                    activity_type=act_type,
                    description=desc,
                    timestamp=activity_time
                )
                activity_records.append(activity)

        # Bulk insert
        db.session.add_all(activity_records)
        print(f"Generated {len(activity_records)} user activities.")

        # 2. Seed DiseaseNews
        print("Generating disease news categories and view counts...")
        
        # Clear existing news first to avoid duplicate news URL keys
        db.session.query(DiseaseNews).delete()
        print("Cleared old disease news.")

        sample_news = [
            {
                "title": "Lonjakan Kasus Demam Berdarah Dengue (DBD) di DKI Jakarta Mencapai 1.200 Kasus",
                "disease_name": "Dengue",
                "summary": "Kementerian Kesehatan mengimbau warga DKI Jakarta untuk waspada dan memperketat Pemberantasan Sarang Nyamuk (PSN) 3M Plus menyusul lonjakan signifikan kasus DBD di lima wilayah kota.",
                "country": "Indonesia",
                "source_name": "Kemenkes RI",
                "source_url": "https://kemkes.go.id/news/dbd-jakarta-2026",
                "alert_level": "medium",
                "badge": "Perlu Diwaspadai",
                "region_scope": "indonesia",
                "trend_score": 85,
                "trend_keyword": "dengue",
                "view_count": 2450
            },
            {
                "title": "WHO Mengeluarkan Peringatan Darurat Global Terkait Wabah Mpox di Kongo",
                "disease_name": "Mpox",
                "summary": "World Health Organization kembali menetapkan penyebaran virus Mpox di Republik Demokratik Kongo sebagai Kedaruratan Kesehatan Masyarakat yang Menjadi Perhatian Internasional (PHEIC).",
                "country": "Kongo",
                "source_name": "WHO",
                "source_url": "https://who.int/emergencies/mpox-2026",
                "alert_level": "high",
                "badge": "Wabah Global",
                "region_scope": "international",
                "trend_score": 110,
                "trend_keyword": "mpox",
                "view_count": 4890
            },
            {
                "title": "Varian Baru Covid-19 JN.1 Terdeteksi di Indonesia, Kemenkes Imbau Disiplin Prokes",
                "disease_name": "Covid-19",
                "summary": "Varian baru Covid-19 JN.1 yang memiliki tingkat penularan lebih cepat dilaporkan telah terdeteksi di beberapa wilayah Indonesia. Pemerintah meminta masyarakat segera melengkapi vaksin booster.",
                "country": "Indonesia",
                "source_name": "Kemenkes RI",
                "source_url": "https://kemkes.go.id/news/covid-jn1-indonesia",
                "alert_level": "medium",
                "badge": "Trending",
                "region_scope": "indonesia",
                "trend_score": 92,
                "trend_keyword": "covid",
                "view_count": 3120
            },
            {
                "title": "Wabah Penyakit Kolera Meluas di Yaman Akibat Krisis Air Bersih",
                "disease_name": "Cholera",
                "summary": "Lebih dari 10.000 kasus dugaan kolera dilaporkan terjadi di Yaman dalam sebulan terakhir. PBB mendesak bantuan obat-obatan dan pasokan air bersih segera dikirim untuk mencegah perluasan wabah.",
                "country": "Yaman",
                "source_name": "CDC",
                "source_url": "https://cdc.gov/outbreaks/cholera-yemen",
                "alert_level": "high",
                "badge": "Wabah Global",
                "region_scope": "international",
                "trend_score": 98,
                "trend_keyword": "cholera",
                "view_count": 1820
            },
            {
                "title": "Kasus Rabies Baru pada Manusia di Nusa Tenggara Timur Meningkat, 5 Orang Meninggal",
                "disease_name": "Rabies",
                "summary": "Pemerintah Provinsi NTT menetapkan status Kejadian Luar Biasa (KLB) Rabies setelah adanya laporan kematian akibat gigitan anjing penular rabies. Stok vaksin antirabies (VAR) didistribusikan massal.",
                "country": "Indonesia",
                "source_name": "Kemenkes RI",
                "source_url": "https://kemkes.go.id/news/rabies-ntt-klb",
                "alert_level": "high",
                "badge": "Perlu Diwaspadai",
                "region_scope": "indonesia",
                "trend_score": 105,
                "trend_keyword": "rabies",
                "view_count": 3890
            },
            {
                "title": "Influenza Musiman Meningkat di Wilayah Jawa Barat Menyusul Masuknya Musim Hujan",
                "disease_name": "Influenza",
                "summary": "Puskesmas di Jawa Barat melaporkan kenaikan kunjungan pasien influenza sebesar 40%. Dokter menyarankan konsumsi vitamin tambahan dan imunisasi influenza tahunan bagi anak-anak dan lansia.",
                "country": "Indonesia",
                "source_name": "Google News ID",
                "source_url": "https://news.google.com/influenza-jabar-2026",
                "alert_level": "low",
                "badge": "Update Terbaru",
                "region_scope": "indonesia",
                "trend_score": 62,
                "trend_keyword": "influenza",
                "view_count": 920
            },
            {
                "title": "Kemenkes Targetkan Eliminasi Penyakit Tuberkulosis (TBC) di Indonesia pada Tahun 2030",
                "disease_name": "Tuberculosis",
                "summary": "Indonesia menempati posisi kedua penderita TBC tertinggi di dunia. Pemerintah meluncurkan gerakan penemuan kasus aktif secara masif dan program terapi pencegahan TBC (TPT) gratis.",
                "country": "Indonesia",
                "source_name": "Kemenkes RI",
                "source_url": "https://kemkes.go.id/news/eliminasi-tbc-2030",
                "alert_level": "medium",
                "badge": "Trending",
                "region_scope": "indonesia",
                "trend_score": 78,
                "trend_keyword": "tbc",
                "view_count": 1640
            },
            {
                "title": "Kasus Penularan Flu Burung (Avian Influenza) pada Mamalia Mengkhawatirkan Para Ilmuwan",
                "disease_name": "Avian Influenza",
                "summary": "CDC memantau transmisi flu burung H5N1 yang menyebar ke sapi perah dan mamalia laut. Meskipun risiko terhadap manusia saat ini rendah, pengawasan terhadap pekerja peternakan terus ditingkatkan.",
                "country": "Amerika Serikat",
                "source_name": "CDC",
                "source_url": "https://cdc.gov/birdflu/h5n1-mammals",
                "alert_level": "medium",
                "badge": "Update Terbaru",
                "region_scope": "international",
                "trend_score": 80,
                "trend_keyword": "bird flu",
                "view_count": 1420
            },
            {
                "title": "Wabah Virus Marburg di Rwanda Terkendali Setelah Kampanye Karantina Ketat",
                "disease_name": "Marburg",
                "summary": "Kementerian Kesehatan Rwanda melaporkan tidak ada kasus baru virus Marburg dalam 14 hari terakhir. WHO memuji kecepatan respon pelacakan kontak erat dan isolasi wilayah terdampak.",
                "country": "Rwanda",
                "source_name": "WHO",
                "source_url": "https://who.int/rwanda-marburg-contained",
                "alert_level": "high",
                "badge": "Trending",
                "region_scope": "international",
                "trend_score": 88,
                "trend_keyword": "marburg",
                "view_count": 2150
            },
            {
                "title": "Pentingnya Imunisasi Dasar Lengkap pada Anak untuk Mencegah Kejadian Luar Biasa Polio",
                "disease_name": "Polio",
                "summary": "Menyusul temuan kasus polio lumpuh layu di beberapa provinsi, Kemenkes meluncurkan Sub Pekan Imunisasi Nasional (Sub PIN) Polio secara serentak untuk semua anak usia 0-7 tahun tanpa memandang status sebelumnya.",
                "country": "Indonesia",
                "source_name": "Kemenkes RI",
                "source_url": "https://kemkes.go.id/news/sub-pin-polio-nasional",
                "alert_level": "high",
                "badge": "Perlu Diwaspadai",
                "region_scope": "indonesia",
                "trend_score": 102,
                "trend_keyword": "polio",
                "view_count": 3540
            }
        ]

        news_records = []
        for n in sample_news:
            # Let's set some random fetched_at and published_at in the last 5 days
            days_ago = random.randint(0, 5)
            pub_date = now - datetime.timedelta(days=days_ago)
            
            news_item = DiseaseNews(
                title=n["title"],
                disease_name=n["disease_name"],
                summary=n["summary"],
                country=n["country"],
                source_name=n["source_name"],
                source_url=n["source_url"],
                alert_level=n["alert_level"],
                badge=n["badge"],
                region_scope=n["region_scope"],
                trend_score=n["trend_score"],
                trend_keyword=n["trend_keyword"],
                view_count=n["view_count"],
                is_trending=n["trend_score"] >= 80,
                published_at=pub_date,
                fetched_at=now,
                is_active=True
            )
            news_records.append(news_item)
            
        db.session.add_all(news_records)
        print(f"Generated {len(news_records)} disease news records.")

        db.session.commit()
        print("Database successfully seeded with analytics data!")

if __name__ == '__main__':
    seed_data()
